"""Insights → Rekrutacja: lejek org-level na danych natywnych NEXUSA.

Zastępuje odczyty z `dr_kpi_body_leasing` (zamrożone na tygodniu 21/2026)
i kroczące okna `_period_start` z `reports.py`.

Trzy decyzje, które trzymają ten moduł uczciwym:

1. **Zero predykatów atrybucji.** Lejek firmowy liczy WSZYSTKIE kamienie
   milowe w oknie. Filtry `credit_user_id IS NOT NULL` i `kpi_eligible IS TRUE`
   należą do warstwy imiennej — użyte tutaj obcinają lejek do ułamka prawdy
   i podają ten ułamek jako pewny (patrz docs/insights-dynareporter-migration-plan.md §4).

2. **Brak `JOIN jobs`, dopóki nie filtrujemy po typie rekrutacji.** Ten JOIN
   gubi kamienie milowe par, których oferta została skasowana — czyli cicho
   zaniża lejek historyczny.

3. **Etapy strukturalnie nieobecne są ODZNACZANE, nie zerowane.** Traffit
   nie mapuje `acceptance`, `client_interview`, `negotiation`, `onboarding`
   ani `prep_call` (`app/services/traffit/mappers.py:404-449`), a nieznane
   typy stanów cicho degraduje do `screening`. Gołe „0" przy „Akceptacja"
   czyta się jako „klienci nas nie akceptują", a znaczy „nie odnotowujemy
   akceptacji". Koperta niesie `coverage`, żeby konsument mógł to napisać.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import ANALYTICS_TIMEZONE, PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set
from app.core.database import get_db
from app.services.funnel_coverage import STAGES_WITHOUT_TRAFFIT_COVERAGE
from app.services.insights_invite_links import (
    compute_invite_link_channels,
    count_invite_link_candidates,
)
from app.services.insights_seniority import compute_seniority, load_thresholds
from app.services.insights_seniority_journal import (
    load_journal_status,
    load_open_regressions,
)
from app.services.insights_team_activity import compute_team_activity

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300

# Kolejność etapów w lejku.
#
# Dwa NIEZALEŻNE powody, dla których etap pokazuje zero — i nie wolno ich
# mylić, bo znaczą co innego:
#
# `in_milestones` — czy etap jest w widoku `analytics_first_milestones`.
#   Widok niesie DOKŁADNIE sześć: verified, cv_sent, interview,
#   client_interview, acceptance, hired (zweryfikowane `pg_get_viewdef`).
#   Reszta lejka musi przyjść z `candidate_stages`, deduplikowana tak samo —
#   inaczej liczby z dwóch źródeł nie dają się porównać.
#
# `mapped_from_traffit` — czy import z Traffita zna ten etap. Wyliczane
#   z `app.services.funnel_coverage` (które wyprowadza to z tabeli mapera),
#   NIE deklarowane tutaj — patrz pętla pod listą. Etap spoza tej listy
#   pokazuje zero, bo NIE JEST ODNOTOWYWANY.
#
# Pomylenie tych flag daje dokładnie defekt, przed którym broni docstring
# modułu: API twierdziłoby, że zero przy „Nowi" to obserwacja, a przy
# „Akceptacja" — brak danych. Jest odwrotnie.
FUNNEL_STAGES: list[dict] = [
    {
        "stage": "new",
        "label": "Nowi / Analiza CV",
        "in_milestones": False,
    },
    {
        "stage": "screening",
        "label": "Screening",
        "in_milestones": False,
    },
    {
        "stage": "verified",
        "label": "Zweryfikowany",
        "in_milestones": True,
    },
    {
        "stage": "prep_call",
        "label": "Preparation Meeting",
        "in_milestones": False,
    },
    {
        "stage": "cv_sent",
        "label": "CV wysłane",
        "in_milestones": True,
    },
    {
        "stage": "interview",
        "label": "Rozmowa",
        "in_milestones": True,
    },
    {
        "stage": "client_interview",
        "label": "Rozmowa u klienta",
        "in_milestones": True,
    },
    {
        "stage": "acceptance",
        "label": "Akceptacja",
        "in_milestones": True,
    },
    {
        "stage": "negotiation",
        "label": "Negocjacje",
        "in_milestones": False,
    },
    {
        "stage": "hired",
        "label": "Zatrudniony",
        "in_milestones": True,
    },
    {
        "stage": "onboarding",
        "label": "Onboarding",
        "in_milestones": False,
    },
    {
        "stage": "rejected",
        "label": "Odrzucony",
        "in_milestones": False,
    },
    {
        "stage": "withdrawn",
        "label": "Wycofany",
        "in_milestones": False,
    },
]

# `mapped_from_traffit` jest POCHODNĄ tabeli mapera, nie deklaracją.
#
# Trzynaście ręcznie utrzymywanych booleanów rozjeżdżało się z rzeczywistością
# przy pierwszej zmianie mapowania, a objaw byłby cichy: etap raportowałby
# „odnotowywany", pokazując zero. Źródło prawdy jest jedno i dzieli je
# z kaflami dashboardu (`app.services.funnel_coverage`).
for _stage in FUNNEL_STAGES:
    _stage["mapped_from_traffit"] = (
        _stage["stage"] not in STAGES_WITHOUT_TRAFFIT_COVERAGE
    )

_STAGE_LOG_STAGES = [x["stage"] for x in FUNNEL_STAGES if not x["in_milestones"]]

# Konwersje liczone z TYCH SAMYCH liczników co kafle wyżej. Gdy mianownik jest
# zerem, wynik to None (luka), nigdy 0.0 — „nie da się policzyć" to co innego
# niż „policzone i wyszło zero".
CONVERSIONS: list[dict] = [
    {
        "key": "verified_to_cv_sent",
        "label": "Weryfikacje → Rekomendacje",
        "numerator": "cv_sent",
        "denominator": "verified",
    },
    {
        "key": "cv_sent_to_interview",
        "label": "Rekomendacje → Rozmowy",
        "numerator": "interview",
        "denominator": "cv_sent",
    },
    {
        "key": "interview_to_hired",
        "label": "Rozmowy → Zatrudnienia",
        "numerator": "hired",
        "denominator": "interview",
    },
    {
        "key": "verified_to_hired",
        "label": "Overall (Weryfikacja → Zatrudnienie)",
        "numerator": "hired",
        "denominator": "verified",
    },
]


def _ratio(numerator: int, denominator: int) -> float | None:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 — konsument musi móc odróżnić „policzone, wyszło zero" od
    „nie było czego dzielić". Świadomie NIE przycinamy też do 100%: konwersja
    powyżej stu procent jest sygnałem, że kolejność etapów nie trzyma się
    kupy (a w danych z Traffita nie trzyma), i ma być widoczna, nie schowana.
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _resolve(kind: str, offset: int, anchor: date | None, date_from, date_to):
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("/funnel")
async def insights_recruitment_funnel(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Lejek rekrutacyjny całej firmy w oknie — bez atrybucji imiennej.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Nie niesie danych
    osobowych: same liczniki etapów.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    # Klucz cache'u NIESIE OKNO. Bez tego liczby jednego okresu wyszłyby pod
    # etykietą drugiego — i nikt by się nie dowiedział, bo obie są wiarygodne.
    cache_key = f"insights:recruitment:funnel:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    params = {"start": resolved.start, "end": resolved.end}

    # Półotwarte [start, end) — ta sama semantyka co w periods.py. Brak górnej
    # granicy (jak w legacy `_period_start`) sprawiał, że „poprzedni miesiąc"
    # oznaczał w praktyce „od poprzedniego miesiąca do dziś".
    rows = (
        (
            await db.execute(
                text(
                    """
                SELECT fm.stage AS stage, count(*) AS cnt
                FROM analytics_first_milestones fm
                WHERE fm.first_reached_at >= :start
                  AND fm.first_reached_at < :end
                GROUP BY fm.stage
                """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )
    counts = {r["stage"]: int(r["cnt"]) for r in rows}

    # Zrodlo 2 — reszta lejka wprost z `candidate_stages`, DEDUPLIKOWANA TAK
    # SAMO jak widok: pierwsze wystapienie per (kandydat, oferta, etap). Bez
    # tego gora lejka liczylaby surowe wiersze, a srodek — pary, i dwie czesci
    # tego samego wykresu nie dalyby sie porownac. Import Traffita dopisuje
    # wiersz na kazde zdarzenie, wiec ponowne wejscie liczyloby sie wielokrotnie.
    log_rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT stage, count(*) AS cnt
                    FROM (
                        SELECT DISTINCT ON (cs.candidate_id, cs.job_id, cs.stage)
                               cs.stage AS stage, cs.moved_at AS moved_at
                        FROM candidate_stages cs
                        WHERE cs.stage::text = ANY(:stages)
                        ORDER BY cs.candidate_id, cs.job_id, cs.stage,
                                 cs.moved_at, cs.id
                    ) firsts
                    WHERE firsts.moved_at >= :start AND firsts.moved_at < :end
                    GROUP BY stage
                    """
                ),
                {**params, "stages": _STAGE_LOG_STAGES},
            )
        )
        .mappings()
        .all()
    )
    for lr in log_rows:
        counts[str(lr["stage"])] = int(lr["cnt"])

    # Pokrycie: ile ruchu w tym oknie powstało W NEXUSIE, a ile przyszło
    # z importu. Dyskryminator to `external_source = 'manual'`, NIE `IS NULL`
    # (kolumna ma ORM-owy default 'manual', a importer wpisuje 'traffit').
    coverage_row = (
        (
            await db.execute(
                text(
                    """
                SELECT
                  count(*) AS total,
                  count(*) FILTER (WHERE cs.external_source = 'manual') AS manual,
                  count(*) FILTER (WHERE cs.moved_by IS NULL) AS unattributed
                FROM candidate_stages cs
                WHERE cs.moved_at >= :start AND cs.moved_at < :end
                """
                ),
                params,
            )
        )
        .mappings()
        .first()
    )

    total_moves = int(coverage_row["total"] or 0) if coverage_row else 0
    manual_moves = int(coverage_row["manual"] or 0) if coverage_row else 0
    unattributed = int(coverage_row["unattributed"] or 0) if coverage_row else 0

    max_count = max([counts.get(s["stage"], 0) for s in FUNNEL_STAGES] + [0])

    stages = [
        {
            "stage": s["stage"],
            "label": s["label"],
            "count": counts.get(s["stage"], 0),
            "mapped_from_traffit": s["mapped_from_traffit"],
            # Skad przyszla liczba — zeby konsument nie zsumowal dwoch zrodel
            # pod jednym naglowkiem, nie wiedzac o tym.
            "source": "milestones" if s["in_milestones"] else "stage_log",
            # Udział względem najliczniejszego etapu — do szerokości paska.
            "share_pct": _ratio(counts.get(s["stage"], 0), max_count),
        }
        for s in FUNNEL_STAGES
    ]

    conversions = [
        {
            "key": c["key"],
            "label": c["label"],
            "numerator": counts.get(c["numerator"], 0),
            "denominator": counts.get(c["denominator"], 0),
            "pct": _ratio(
                counts.get(c["numerator"], 0), counts.get(c["denominator"], 0)
            ),
        }
        for c in CONVERSIONS
    ]

    result = {
        "period": resolved.as_payload(),
        "stages": stages,
        "conversions": conversions,
        "coverage": {
            "stage_moves_total": total_moves,
            "stage_moves_manual": manual_moves,
            "manual_pct": _ratio(manual_moves, total_moves),
            "unattributed_moves": unattributed,
            # Etapy, których import Traffita w ogóle nie zna. Konsument MUSI
            # to pokazać przy zerach, inaczej brak ewidencji przeczyta się
            # jako brak zjawiska.
            "stages_not_mapped_from_traffit": [
                s["stage"] for s in FUNNEL_STAGES if not s["mapped_from_traffit"]
            ],
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/available-periods")
async def insights_available_periods(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    granularity: str = Query("month", pattern="^(week|month|quarter)$"),
    limit: int = Query(24, ge=1, le=120),
):
    """Okresy, w których w ogóle są dane — do dropdownu kotwicy.

    Źródłem jest `analytics_first_milestones`, NIGDY `dr_kpi_body_leasing`
    (to drugie stoi na tygodniu 21/2026 i podsunęłoby listę kończącą się
    w maju jako „wszystko, co mamy").
    """
    unit = {"week": "week", "month": "month", "quarter": "quarter"}[granularity]
    rows = (
        (
            await db.execute(
                text(
                    f"""
                SELECT date_trunc('{unit}', fm.first_reached_at AT TIME ZONE 'Europe/Warsaw')
                         AS bucket,
                       count(*) AS cnt
                FROM analytics_first_milestones fm
                GROUP BY 1
                ORDER BY 1 DESC
                LIMIT :limit
                """
                ),
                {"limit": limit},
            )
        )
        .mappings()
        .all()
    )

    return {
        "granularity": granularity,
        "periods": [
            {"start": r["bucket"].date().isoformat(), "milestones": int(r["cnt"])}
            for r in rows
            if r["bucket"] is not None
        ],
    }


@router.get("/time-to-hire")
async def insights_time_to_hire(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("quarter", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0),
    anchor: date | None = Query(None),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    min_hires: int = Query(1, ge=1, le=50),
):
    """Czas od pierwszego ruchu pary (kandydat × oferta) do zatrudnienia.

    Naprawia zaniżenie z `phase3.py:404-432`: tamta implementacja pobiera
    wyłącznie etapy Z OKNA (`WHERE moved_at >= since`), a potem bierze
    `items[0].moved_at` jako początek procesu. Dla kandydata, którego proces
    zaczął się PRZED oknem, początkiem staje się pierwszy etap wewnątrz okna,
    więc czas wychodzi krótszy, niż był naprawdę — i to tym bardziej, im
    dłużej trwała rekrutacja. Tutaj startu szukamy w CAŁEJ historii pary;
    oknem ograniczone jest wyłącznie samo zatrudnienie.

    Mediana i p90 zamiast średniej: rozkład ma długi ogon (pojedyncza
    rekrutacja ciągnąca się rok podnosi średnią całemu zespołowi).
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)
    cache_key = f"insights:recruitment:tth:v1:{resolved.cache_suffix}:{min_hires}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = (
        (
            await db.execute(
                text(
                    """
                WITH hired AS (
                    -- Kanoniczny placement (D2): PIERWSZE 'hired' dla pary
                    -- (kandydat, oferta). candidate_stages nie ma unikalnosci
                    -- na (candidate_id, job_id, stage), a import Traffita
                    -- dopisuje wiersz na kazde zdarzenie — liczenie surowych
                    -- wierszy dublowaloby ponowne wejscia na etap.
                    SELECT fm.candidate_id, fm.job_id, fm.first_reached_at,
                           fm.first_moved_by
                    FROM analytics_first_milestones fm
                    WHERE fm.stage = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                ),
                started AS (
                    -- Poczatek procesu z CALEJ historii pary, bez ograniczenia
                    -- oknem. To jest ta poprawka.
                    SELECT cs.candidate_id, cs.job_id, min(cs.moved_at) AS started_at
                    FROM candidate_stages cs
                    JOIN hired h
                      ON h.candidate_id = cs.candidate_id
                     AND h.job_id IS NOT DISTINCT FROM cs.job_id
                    GROUP BY cs.candidate_id, cs.job_id
                ),
                spans AS (
                    SELECT h.first_moved_by AS user_id,
                           GREATEST(
                               0,
                               EXTRACT(EPOCH FROM (h.first_reached_at - s.started_at))
                               / 86400.0
                           ) AS days
                    FROM hired h
                    JOIN started s
                      ON s.candidate_id = h.candidate_id
                     AND s.job_id IS NOT DISTINCT FROM h.job_id
                )
                SELECT user_id,
                       count(*) AS hires,
                       percentile_cont(0.5) WITHIN GROUP (ORDER BY days) AS median_days,
                       percentile_cont(0.9) WITHIN GROUP (ORDER BY days) AS p90_days
                FROM spans
                GROUP BY user_id
                """
                ),
                {"start": resolved.start, "end": resolved.end},
            )
        )
        .mappings()
        .all()
    )

    user_ids = [int(r["user_id"]) for r in rows if r["user_id"] is not None]
    names: dict[int, str] = {}
    if user_ids:
        name_rows = (
            (
                await db.execute(
                    text("SELECT id, name FROM users WHERE id = ANY(:ids)"),
                    {"ids": user_ids},
                )
            )
            .mappings()
            .all()
        )
        names = {int(r["id"]): r["name"] for r in name_rows}

    entries = []
    unattributed_hires = 0
    for r in rows:
        hires = int(r["hires"])
        if r["user_id"] is None:
            # Kamien, ktorego nie da sie przypisac nikomu — operator Traffita
            # bez dopasowania po e-mailu. NIE wolno go po cichu wyciac: suma
            # kolumny przestalaby sie zgadzac z lejkiem, a tabela wygladalaby
            # na zepsuta. Raportujemy osobno.
            unattributed_hires += hires
            continue
        if hires < min_hires:
            continue
        entries.append(
            {
                "user_id": int(r["user_id"]),
                "name": names.get(int(r["user_id"]), "—"),
                "hires": hires,
                "median_days": round(float(r["median_days"]), 1)
                if r["median_days"] is not None
                else None,
                "p90_days": round(float(r["p90_days"]), 1)
                if r["p90_days"] is not None
                else None,
            }
        )
    entries.sort(key=lambda e: (-e["hires"], e["name"]))

    total_hires = sum(e["hires"] for e in entries) + unattributed_hires
    result = {
        "period": resolved.as_payload(),
        "entries": entries,
        "totals": {
            "hires": total_hires,
            "attributed_hires": total_hires - unattributed_hires,
            # Ta liczba MUSI byc wyrenderowana obok sumy kolumny. Bez niej
            # tabela per osoba nie zgadza sie z lejkiem i czyta sie jak blad.
            "unattributed_hires": unattributed_hires,
        },
        "min_hires": min_hires,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/team-activity")
async def insights_team_activity(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
    limit: int = Query(20, ge=1, le=50),
):
    """Imienny ranking aktywności zespołu w oknie.

    UWAGA — ta odpowiedź niesie DANE IMIENNE (kto ile zrobił) i jest dostępna
    dla KAŻDEJ zalogowanej roli. To jest ŚWIADOME, nie przeoczenie: decyzja D7
    (Artur, 2026-08-31, docs/insights-dynareporter-migration-plan.md §0 D7)
    otwiera całe `/insights` dla wszystkich zalogowanych. Nie „napraw" tego,
    podstawiając tu `require_capability(VIEW_RECRUITMENT_RANKING)` — ta
    capability steruje 40+ innymi powierzchniami i jej semantyka jest inna;
    powierzchnia legacy (`/api/activities/leaderboard`) zostaje na niej bez
    zmian. Zawężenie zaczyna się od zmiany decyzji D7, nie stąd.

    Różnica wobec legacy nie jest kosmetyczna: tamten endpoint liczy okno
    KROCZĄCE (`now - 30 dni`, bez sufitu), więc „poprzedni miesiąc" znaczy tam
    „od poprzedniego miesiąca do dziś". Tutaj okno jest kalendarzowe
    i półotwarte `[start, end)`.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    # Klucz NIESIE OKNO i `limit` — obcięta lista pod kluczem pełnej dałaby
    # liczby jednego zapytania pod etykietą drugiego.
    cache_key = f"insights:recruitment:team-activity:v1:{resolved.cache_suffix}:{limit}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = await compute_team_activity(
        db, since=resolved.start, until=resolved.end, limit=limit
    )

    # Mianownik paska: najaktywniejsza osoba w oknie. Pusty ranking daje zero,
    # a `_ratio` zamienia je na `None` — pasek bez skali to brak wartości,
    # nie zero aktywności.
    max_actions = max([r.total_actions for r in rows] + [0])

    entries = [
        {
            "rank": rank,
            "user_id": r.user_id,
            "name": r.user_name,
            "candidates_added": r.candidates_added,
            "screenings": r.screenings,
            "interviews": r.interviews,
            "placements": r.placements,
            "calls": r.calls,
            "total_actions": r.total_actions,
            "share_pct": _ratio(r.total_actions, max_actions),
        }
        for rank, r in enumerate(rows, start=1)
    ]

    result = {
        "period": resolved.as_payload(),
        "limit": limit,
        "entries": entries,
        "totals": {
            "users": len(entries),
            # Suma WIDOCZNYCH wierszy, nie całej tabeli `user_activities` —
            # kafel liczony z innego zbioru niż lista pod nim nie daje się
            # sprawdzić wzrokiem.
            "actions": sum(e["total_actions"] for e in entries),
        },
        "coverage": {
            "source": "user_activities",
            # Bez tego zdania pusty ranking czyta się jako „zespół nic nie
            # robił". `user_activities` zapisuje wyłącznie czynności wykonane
            # W NEXUSIE — import z Traffita nie tworzy tam ani jednego wiersza.
            "note": (
                "Liczone są wyłącznie czynności wykonane w NEXUSIE. "
                "Ruch zaimportowany z Traffita nie zasila tej tabeli, więc "
                "zero przy osobie znaczy „nie pracowała w NEXUSIE”, "
                "a nie „nie pracowała”."
            ),
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/invite-links")
async def insights_invite_links(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Skuteczność kanałów aplikacyjnych (linki z etykietą) w oknie.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Legacy
    `/api/reports/invite-links` zostaje na swoich czterech rolach i na swoim
    kroczącym oknie — ten endpoint go nie zmienia, tylko liczy to samo
    kalendarzowo i z uczciwą konwencją zerowego mianownika.

    Trzy różnice wobec legacy, każda naprawiająca konkretną nieprawdę:

    1. Okno jest półotwarte `[start, end)`, a nie kroczące bez sufitu — legacy
       nie zna ani granulacji rocznej, ani przesunięcia (`offset`) i zawsze
       pokazuje okres BIEŻĄCY.
    2. `conversion_pct` przy zerze linków to `None`, nie `0.0`. „Nie było czego
       dzielić" to co innego niż „policzone i wyszło zero".
    3. `window_scope` mówi WPROST, co okno filtruje. Bez tego liczba aplikacji
       wygląda na „aplikacje w tym okresie", a jest sumą liczników na linkach
       ZAŁOŻONYCH w tym okresie — patrz niżej.
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    cache_key = f"insights:recruitment:invite-links:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = await compute_invite_link_channels(
        db, since=resolved.start, until=resolved.end
    )
    candidates = await count_invite_link_candidates(
        db, since=resolved.start, until=resolved.end
    )

    channels = [
        {
            # Etykieta do wyświetlenia ORAZ flaga, bo etykieta „Bez etykiety"
            # jest legalną nazwą kanału i sam string nie pozwoliłby odróżnić
            # kubełka linków nieopisanych od kanału tak nazwanego.
            "channel": r.channel or "Bez etykiety",
            "unlabelled": r.channel is None,
            "links_count": r.links_count,
            "applications": r.applications,
            "conversion_pct": _ratio(r.applications, r.links_count),
            "last_used_at": r.last_used_at.isoformat() if r.last_used_at else None,
        }
        for r in rows
    ]

    total_links = sum(c["links_count"] for c in channels)
    total_applications = sum(c["applications"] for c in channels)

    result = {
        "period": resolved.as_payload(),
        "channels": channels,
        # Kafle to FOLD po tej samej liście, którą niesie `channels` — kafel
        # będący sumą innych liczb niż widoczne pod nim nie daje się
        # zweryfikować wzrokiem.
        "totals": {
            "links": total_links,
            "applications": total_applications,
            "candidates": candidates,
            "conversion_pct": _ratio(total_applications, total_links),
        },
        "window_scope": {
            "channels": "link_created_at",
            "candidates": "candidate_created_at",
            # `use_count` jest licznikiem NA LINKU, kumulatywnym od jego
            # powstania — nie da się go pociąć oknem bez tabeli zdarzeń.
            "applications_are_lifetime_per_link": True,
            "note": (
                "Okno filtruje LINKI po dacie utworzenia. Licznik aplikacji "
                "jest kumulatywny na linku, więc link założony w tym oknie "
                "wnosi wszystkie swoje aplikacje — także sprzed granicy okna. "
                "Oknem przycięta uczciwie jest wyłącznie liczba unikalnych "
                "kandydatów."
            ),
        },
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/seniority")
async def insights_seniority(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    as_of: date | None = Query(
        None,
        description=(
            "Dzień, na który liczymy poziom (domyślnie dziś w Europe/Warsaw). "
            "Placementy późniejsze są odcinane."
        ),
    ),
):
    """Ścieżka rozwoju: junior → senior → expert z liczby placementów.

    Dostępne dla KAŻDEJ zalogowanej roli (decyzja D7,
    docs/insights-dynareporter-migration-plan.md §0). Odpowiedź niesie DANE
    IMIENNE — to jest świadome, tak samo jak w `/team-activity` obok.

    Poziom jest LICZONY PRZY ODCZYCIE, nigdy przechowywany. Pełne uzasadnienie
    (łącznie z tym, dlaczego nie ma degradacji i dlaczego konta-widma z importu
    Traffita są odcinane przez `is_active`) siedzi w docstringu
    `app/services/insights_seniority.py` — nie powielam go tutaj, żeby dwie
    kopie tego samego wyjaśnienia nie rozjechały się przy pierwszej zmianie.

    Konsekwencja do zapamiętania: poziom zmienia się wtedy, gdy zmienia się
    HISTORIA ATRYBUCJI (np. import dopisze zaległe `hired` innej osobie), a nie
    wtedy, gdy ktoś coś dziś zrobił.
    """
    # Domyślny dzień w kalendarzu analitycznym, nie w UTC. O 00:30 czasu
    # polskiego `date.today()` w UTC pokazuje jeszcze wczoraj — a wtedy
    # placement sprzed pół godziny wypadałby z okna.
    effective_as_of = as_of or datetime.now(ZoneInfo(ANALYTICS_TIMEZONE)).date()

    # Progi czytamy PRZED cache'em, bo wchodzą w klucz: inaczej zmiana progu
    # przez admina byłaby niewidoczna przez cały TTL, a poziom jest z progu
    # wyliczany (patrz `SeniorityThresholds.cache_suffix`).
    thresholds = await load_thresholds(db)

    cache_key = (
        "insights:recruitment:seniority:v1"
        f":{effective_as_of.isoformat()}:{thresholds.cache_suffix}"
    )
    # Regresje czytamy ZAWSZE, także przy trafieniu w cache. Dziennik zapisuje
    # pętla dobowa; gdyby ostrzeżenie siedziało pod tym samym TTL co wyliczenia,
    # nocna regresja byłaby niewidoczna aż do wygaśnięcia cache'u — a to jest
    # dokładnie ta informacja, która nie może się spóźnić.
    # `None` (a NIE pusta lista) gdy dziennika nie da się odczytać. Trzy stany
    # muszą być rozróżnialne: „brak regresji", „są regresje" i „nie wiem".
    # Pusta lista przy awarii to awaria udająca wynik — czytelnik zobaczyłby
    # ciszę i przeczytał ją jako „nikomu nic nie spadło".
    #
    # Wyjątek jest ŁAPANY, a nie propagowany: ostrzeżenie jest poboczne wobec
    # tabeli poziomów i nie ma powodu, żeby brak jednej tabeli (prodowy alembic
    # bywa osierocony) gasił CAŁĄ sekcję, która działała bez tego dziennika.
    # DWA osobne bloki, nie jeden. Wspólny `try` zerował listę regresji, gdy
    # padało zapytanie o ŚWIEŻOŚĆ — czyli wyrzucał dane, które już mieliśmy
    # w ręku, i chował realny spadek poziomu za komunikatem „nie wiadomo".
    #
    # Sesja po nieudanym zapytaniu jest w stanie „aborted"; bez `rollback()`
    # KAŻDE kolejne zapytanie w tym żądaniu pada na InFailedSqlTransaction,
    # czyli poprawka wywracałaby to, co miała uratować.
    journal_status: dict | None
    try:
        regressions: list[dict] | None = await load_open_regressions(db)
    except Exception:  # noqa: BLE001
        logger.exception("nie udało się odczytać dziennika seniority")
        await db.rollback()
        regressions = None
        journal_status = None
    else:
        # Pusta lista regresji NIE dowodzi, że pętla działa — dowodzi tego
        # dopiero data ostatniej obserwacji. Bez niej cisza na ekranie znaczy
        # naraz „sprawdzono, jest dobrze" i „nigdy nie sprawdzono".
        try:
            journal_status = await load_journal_status(db)
        except Exception:  # noqa: BLE001
            logger.exception("nie udało się odczytać świeżości dziennika")
            await db.rollback()
            journal_status = None

    cached = await cache_get(cache_key)
    if cached is not None:
        return {**cached, "regressions": regressions, "journal": journal_status}

    computed = await compute_seniority(db, as_of=effective_as_of, thresholds=thresholds)

    result = {
        "as_of": computed.as_of.isoformat(),
        # Progi wychodzą na zewnątrz, żeby UI napisał regułę słowami
        # („6 placementów w 6 miesięcy"). Sam pasek postępu nie mówi, ile
        # trzeba — a osoba, której to dotyczy, ma prawo znać regułę.
        "thresholds": computed.thresholds.as_payload(),
        "window": {
            "senior": computed.senior_window.as_payload(),
            "expert": computed.expert_window.as_payload(),
        },
        "entries": [row.as_payload() for row in computed.rows],
        "totals": {
            "users": len(computed.rows),
            "levels": {
                level: sum(1 for r in computed.rows if r.level == level)
                for level in ("junior", "senior", "expert")
            },
        },
        "coverage": {
            # Placementy spoza tabeli. Bez tych dwóch liczb suma kolumny nie
            # zgadza się z lejkiem i tabela czyta się jak zepsuta zamiast jak
            # niekompletna (decyzja D1).
            "unattributed_placements": computed.unattributed_placements,
            "outside_pool_placements": computed.outside_pool_placements,
            "note": (
                "Poziom liczymy wyłącznie z placementów przypisanych do "
                "aktywnych kont w rolach sourcer / TAC / rekruter. Placementy "
                "bez przypisanego operatora oraz przypisane do kont spoza tej "
                "puli (w tym kont założonych przez import Traffita dla "
                "operatorów bez odpowiednika w NEXUSIE) są liczone osobno."
            ),
        },
        # Osoby, którym poziom SPADŁ — czyli którym historia atrybucji zmieniła
        # się pod nogami. Moduł liczący nie degraduje poziomu upływem czasu
        # (patrz `insights_seniority`, decyzja 2), więc spadek nigdy nie jest
        # normalnym przebiegiem kariery i musi być widoczny, a nie tylko
        # możliwy do wygrzebania z bazy.
        "regressions": regressions,
        # `last_observed_at: null` = pętla dobowa nigdy nic nie zapisała.
        # Front musi to POWIEDZIEĆ, bo inaczej niedziałający dziennik wygląda
        # identycznie jak dziennik bez regresji.
        "journal": journal_status,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result
