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
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import PeriodError, resolve_period
from app.api.deps import CurrentUser
from app.core.cache import cache_get, cache_set
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter()

CACHE_TTL_SECONDS = 300

# Kolejność etapów w lejku. Klucz = wartość w `analytics_first_milestones.stage`.
# `mapped_from_traffit=False` oznacza etap, którego import Traffita NIE zna —
# jego zero to brak ewidencji, nie brak zjawiska.
FUNNEL_STAGES: list[dict] = [
    {"stage": "new", "label": "Nowi / Analiza CV", "mapped_from_traffit": True},
    {"stage": "screening", "label": "Screening", "mapped_from_traffit": True},
    {"stage": "verified", "label": "Zweryfikowany", "mapped_from_traffit": True},
    {
        "stage": "prep_call",
        "label": "Preparation Meeting",
        "mapped_from_traffit": False,
    },
    {"stage": "cv_sent", "label": "CV wysłane", "mapped_from_traffit": True},
    {"stage": "interview", "label": "Rozmowa", "mapped_from_traffit": True},
    {
        "stage": "client_interview",
        "label": "Rozmowa u klienta",
        "mapped_from_traffit": False,
    },
    {"stage": "acceptance", "label": "Akceptacja", "mapped_from_traffit": False},
    {"stage": "negotiation", "label": "Negocjacje", "mapped_from_traffit": False},
    {"stage": "hired", "label": "Zatrudniony", "mapped_from_traffit": True},
    {"stage": "onboarding", "label": "Onboarding", "mapped_from_traffit": False},
    {"stage": "rejected", "label": "Odrzucony", "mapped_from_traffit": True},
    {"stage": "withdrawn", "label": "Wycofany", "mapped_from_traffit": True},
]

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
