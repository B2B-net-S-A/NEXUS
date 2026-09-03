"""Insights → Rekrutacja: statystyki roczne i analiza placementów.

Odtwarza z DynaReportera trzy kafle zakładki Rekrutacja: „Progress Zespołu",
„Efektywność Lejka" i „Analiza Placementów" — na danych natywnych NEXUSA.

Cztery decyzje, które trzymają ten moduł uczciwym:

1. **Placement = D2.** PIERWSZE `hired` dla pary (kandydat, oferta), czytane
   z widoku `analytics_first_milestones`. `candidate_stages` nie ma
   unikalności na (candidate_id, job_id, stage), a import Traffita dopisuje
   wiersz na każde zdarzenie — liczenie surowych wierszy dublowałoby powroty
   na etap. Nigdy nie liczymy stąd surowych wierszy `candidate_stages`.

2. **Miesiąc bez mianownika to LUKA, nie zero.** `_ratio` zwraca `None`, więc
   wykres konwersji przerywa linię zamiast spaść do zera. „Nie da się
   policzyć" i „policzone, wyszło zero" to dwa różne zdania o zespole.

3. **Konwersje NIE SĄ przycinane do 100%.** W danych z importu kolejność
   etapów się nie trzyma (rekomendacja bez wcześniejszej weryfikacji w tym
   samym miesiącu, kandydat zatrudniony po rozmowie sprzed okna), więc wynik
   potrafi przekroczyć sto procent. To jest sygnał o jakości danych i ma być
   widoczny, a nie schowany pod sufitem osi.

4. **Miesiące, które się jeszcze nie zaczęły, NIE MAJĄ wiersza.** Zero
   za listopad, oglądane we wrześniu, rysuje linię spadającą do zera — czyta
   się jako zapaść zespołu, a znaczy „ten miesiąc jeszcze nie nastał".
   Miesiąc w toku zostaje, ale jest oznaczony `is_partial`.
"""

import logging
from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.periods import ANALYTICS_TIMEZONE, PeriodError, resolve_period
from app.services.metric_definitions import FIRST_HIRED_PER_CANDIDATE_JOB
from app.api.deps import CurrentUser
from app.api.section_access import INSIGHTS_SECTION_DEPENDENCIES
from app.core.cache import cache_get, cache_set
from app.core.database import get_db

logger = logging.getLogger(__name__)

router = APIRouter(dependencies=INSIGHTS_SECTION_DEPENDENCIES)

CACHE_TTL_SECONDS = 300

_TZ = ZoneInfo(ANALYTICS_TIMEZONE)

# Serie miesięczne „Progress Zespołu". Wszystkie cztery etapy SĄ w widoku
# `analytics_first_milestones` (verified, cv_sent, interview, client_interview,
# acceptance, hired) — dlatego ten wykres nie musi mieszać dwóch źródeł, jak
# musi lejek w `insights_recruitment.py`.
#
# `axis` jest częścią kontraktu, a nie kosmetyką: weryfikacje idą w setkach,
# placementy w dziesiątkach. Na jednej osi placementy leżą płasko przy zerze
# i wykres twierdzi, że nic się nie dzieje.
YEARLY_SERIES: list[dict] = [
    {"key": "verified", "label": "Weryfikacje", "stage": "verified", "axis": "left"},
    {"key": "cv_sent", "label": "Rekomendacje", "stage": "cv_sent", "axis": "left"},
    {"key": "interview", "label": "Interviews", "stage": "interview", "axis": "left"},
    {"key": "hired", "label": "Placements", "stage": "hired", "axis": "right"},
]

_SERIES_STAGES = [s["stage"] for s in YEARLY_SERIES]

# Konwersje liczone z TYCH SAMYCH liczników co serie wyżej — dwa wykresy nad
# sobą muszą dać się porównać wzrokiem.
YEARLY_CONVERSIONS: list[dict] = [
    {
        "key": "verified_to_cv_sent",
        "label": "Weryfikacje → Rekomendacje",
        "numerator": "cv_sent",
        "denominator": "verified",
    },
    {
        "key": "cv_sent_to_interview",
        "label": "Rekomendacje → Interviews",
        "numerator": "interview",
        "denominator": "cv_sent",
    },
    {
        "key": "interview_to_hired",
        "label": "Interviews → Placements",
        "numerator": "hired",
        "denominator": "interview",
    },
    {
        "key": "verified_to_hired",
        "label": "Overall (Weryfikacja → Placement)",
        "numerator": "hired",
        "denominator": "verified",
    },
]

# Podpis wiersza bez atrybucji. Import Traffita zostawia `moved_by` puste dla
# ruchu sprzed NEXUSA, a takich placementów jest w bazie większość. Wycięcie
# ich z rozbicia sprawiłoby, że donut nie sumuje się do kafla obok — czyli
# dwie liczby o tym samym pod jednym nagłówkiem.
UNATTRIBUTED_LABEL = "(nieprzypisane)"
NO_CLIENT_LABEL = "(bez klienta)"

# Nazwa miesiąca na oś X. `strftime("%b")` zależy od locale kontenera, więc
# etykieta z serwera byłaby raz polska, raz angielska, w zależności od obrazu.
MONTH_LABEL_PL: tuple[str, ...] = (
    "sty",
    "lut",
    "mar",
    "kwi",
    "maj",
    "cze",
    "lip",
    "sie",
    "wrz",
    "paź",
    "lis",
    "gru",
)


def _ratio(numerator: int, denominator: int) -> float | None:
    """Udział procentowy albo ``None`` przy zerowym mianowniku.

    NIE zwraca 0.0 (patrz punkt 2 docstringu modułu) i NIE przycina do 100
    (punkt 3). Lustro `_ratio` z `insights_recruitment.py` — ta sama reguła
    musi obowiązywać na obu wykresach, inaczej ten sam miesiąc pokazuje raz
    „—", raz „0%".
    """
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _resolve(
    kind: str,
    offset: int,
    anchor: date | None,
    date_from: date | None,
    date_to: date | None,
):
    try:
        return resolve_period(
            kind, offset=offset, anchor=anchor, date_from=date_from, date_to=date_to
        )
    except PeriodError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


def _month_starts(start: datetime, end: datetime) -> list[date]:
    """Pierwsze dni miesięcy w oknie [start, end), czasem lokalnym Warszawy."""
    first = start.astimezone(_TZ).date().replace(day=1)
    last_exclusive = end.astimezone(_TZ).date()
    out: list[date] = []
    cursor = first
    while cursor < last_exclusive:
        out.append(cursor)
        cursor = (
            date(cursor.year + 1, 1, 1)
            if cursor.month == 12
            else date(cursor.year, cursor.month + 1, 1)
        )
    return out


@router.get("/yearly-stats")
async def insights_yearly_stats(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    year: int | None = Query(
        None,
        ge=2000,
        le=2100,
        description="Rok kalendarzowy (Europe/Warsaw). Domyślnie bieżący.",
    ),
):
    """Dwanaście punktów miesięcznych roku: cztery serie + cztery konwersje.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Nie niesie danych
    osobowych: same liczniki etapów.

    Świadomie NIE przyjmuje okna z `PeriodPicker`a, tak jak sekcja seniority.
    Wykres dwunastu punktów sterowany oknem „miesiąc" zwinąłby się do jednego
    punktu i przestałby być wykresem — a to jest ten sam parametr, którym
    użytkownik steruje resztą zakładki, więc pomyłka byłaby codzienna.
    """
    reference = datetime.now(_TZ)
    target_year = year if year is not None else reference.year
    # `resolve_period` zamiast ręcznej arytmetyki: granice roku (i ich strefa)
    # mają jedno źródło w całym /insights.
    resolved = _resolve("year", 0, date(target_year, 1, 1), None, None)

    # Klucz cache'u NIESIE OKNO — inaczej liczby jednego roku wyszłyby pod
    # etykietą drugiego i nikt by się nie dowiedział, bo obie są wiarygodne.
    # Niesie też bieżący miesiąc: lista miesięcy „już rozpoczętych" zmienia
    # się z upływem czasu, więc odpowiedź sprzed pierwszego stycznia nie
    # opisuje tego samego zbioru co odpowiedź z drugiego.
    cache_key = (
        f"insights:charts:yearly:v1:{resolved.cache_suffix}"
        f":{reference.year}-{reference.month:02d}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT date_trunc(
                               'month',
                               fm.first_reached_at AT TIME ZONE 'Europe/Warsaw'
                           )::date AS month,
                           fm.stage::text AS stage,
                           count(*) AS cnt
                    FROM analytics_first_milestones fm
                    WHERE fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                      AND fm.stage::text = ANY(:stages)
                    GROUP BY 1, 2
                    """
                ),
                {
                    "start": resolved.start,
                    "end": resolved.end,
                    "stages": _SERIES_STAGES,
                },
            )
        )
        .mappings()
        .all()
    )

    by_month: dict[date, dict[str, int]] = {}
    for r in rows:
        bucket = by_month.setdefault(r["month"], {})
        bucket[str(r["stage"])] = int(r["cnt"])

    current_month_start = reference.date().replace(day=1)
    months: list[dict] = []
    totals = {s["key"]: 0 for s in YEARLY_SERIES}

    for month_start in _month_starts(resolved.start, resolved.end):
        # Miesiąc, który się jeszcze nie zaczął, NIE dostaje wiersza (punkt 4
        # docstringu modułu). Zero za przyszłość to nie obserwacja.
        if month_start > current_month_start:
            continue
        counts = by_month.get(month_start, {})
        row: dict = {
            "month": month_start.isoformat(),
            "label": MONTH_LABEL_PL[month_start.month - 1],
            "is_partial": month_start == current_month_start,
        }
        for s in YEARLY_SERIES:
            value = int(counts.get(s["stage"], 0))
            row[s["key"]] = value
            totals[s["key"]] += value
        for c in YEARLY_CONVERSIONS:
            row[f"conv_{c['key']}"] = _ratio(
                int(counts.get(c["numerator"], 0)),
                int(counts.get(c["denominator"], 0)),
            )
        months.append(row)

    result = {
        "period": resolved.as_payload(),
        "year": target_year,
        "months": months,
        # Metadane serii jadą z serwera razem z danymi: etykieta i przypisanie
        # osi to część definicji metryki, nie ozdoba. Rozjazd nazw między
        # legendą a liczbą jest niewykrywalny wzrokiem.
        "series": [
            {"key": s["key"], "label": s["label"], "axis": s["axis"]}
            for s in YEARLY_SERIES
        ],
        "conversion_series": [
            {"key": f"conv_{c['key']}", "label": c["label"]} for c in YEARLY_CONVERSIONS
        ],
        "totals": totals,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result


@router.get("/placement-analysis")
async def insights_placement_analysis(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(day|week|month|quarter|year|custom)$"),
    offset: int = Query(0, description="0 = bieżący okres, -1 = poprzedni zamknięty"),
    anchor: date | None = Query(None, description="dowolny dzień wewnątrz okresu"),
    date_from: date | None = Query(None),
    date_to: date | None = Query(None),
):
    """Rozbicie placementów okna na osoby i klientów + trzy liczby zbiorcze.

    Dostępne dla KAŻDEGO zalogowanego (decyzja D7). Niesie imiona i nazwiska
    osób, którym przypisano placement — świadomie, zgodnie z D7
    (docs/insights-dynareporter-migration-plan.md §0).
    """
    resolved = _resolve(period, offset, anchor, date_from, date_to)

    cache_key = f"insights:charts:placements:v1:{resolved.cache_suffix}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    params = {"start": resolved.start, "end": resolved.end}

    people_rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT fm.first_moved_by AS user_id,
                           u.name AS user_name,
                           count(*) AS cnt
                    FROM analytics_first_milestones fm
                    LEFT JOIN users u ON u.id = fm.first_moved_by
                    WHERE fm.stage = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    GROUP BY 1, 2
                    ORDER BY count(*) DESC, 2 NULLS LAST
                    """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    # LEFT JOIN, nie INNER: kamień milowy pary, której oferta zniknęła z bazy,
    # nadal jest placementem. INNER wyciąłby go z donuta, ale nie z kafla
    # „Suma placementów" — donut przestałby sumować się do liczby nad sobą,
    # co czyta się jak błąd zaokrąglenia, a jest utratą wiersza.
    client_rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT c.id AS client_id,
                           c.name AS client_name,
                           (j.id IS NULL) AS job_missing,
                           count(*) AS cnt
                    FROM analytics_first_milestones fm
                    LEFT JOIN jobs j ON j.id = fm.job_id
                    LEFT JOIN clients c ON c.id = j.client_id
                    WHERE fm.stage = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    GROUP BY 1, 2, 3
                    ORDER BY count(*) DESC, 2 NULLS LAST
                    """
                ),
                params,
            )
        )
        .mappings()
        .all()
    )

    total = sum(int(r["cnt"]) for r in people_rows)

    by_person = [
        {
            "user_id": r["user_id"],
            # Konto skasowane z `users` zostawia atrybucję bez nazwiska.
            # Pusty podpis w legendzie czyta się jak błąd wykresu, więc
            # nazywamy to wprost.
            "name": (
                (r["user_name"] or "").strip()
                or (
                    UNATTRIBUTED_LABEL
                    if r["user_id"] is None
                    else f"Użytkownik #{r['user_id']}"
                )
            ),
            "placements": int(r["cnt"]),
            "share_pct": _ratio(int(r["cnt"]), total),
            "attributed": r["user_id"] is not None,
        }
        for r in people_rows
    ]

    # Klient bez wiersza w `clients` i placement bez oferty lądują w tym samym
    # koszyku „(bez klienta)" — z osobnym licznikiem `placements_without_job`,
    # żeby dało się odróżnić lukę w danych od oferty bez przypisanego klienta.
    by_client_acc: dict[int | None, dict] = {}
    placements_without_job = 0
    for r in client_rows:
        if r["job_missing"]:
            placements_without_job += int(r["cnt"])
        key = r["client_id"]
        entry = by_client_acc.setdefault(
            key,
            {
                "client_id": key,
                "name": (r["client_name"] or "").strip() or NO_CLIENT_LABEL,
                "placements": 0,
            },
        )
        entry["placements"] += int(r["cnt"])

    by_client = sorted(
        (
            {
                **entry,
                "share_pct": _ratio(entry["placements"], total),
                "attributed": entry["client_id"] is not None,
            }
            for entry in by_client_acc.values()
        ),
        key=lambda e: (-e["placements"], e["name"]),
    )

    result = {
        "period": resolved.as_payload(),
        "totals": {
            # Kafel „Osoby z placementami" liczy WYŁĄCZNIE atrybuowane wiersze:
            # „(nieprzypisane)" to nie jest osoba i doliczenie go zawyżałoby
            # zespół o jeden fantom.
            "people": sum(1 for p in by_person if p["attributed"]),
            "placements": total,
            "clients": sum(1 for c in by_client if c["attributed"]),
            "unattributed_placements": sum(
                p["placements"] for p in by_person if not p["attributed"]
            ),
            "placements_without_job": placements_without_job,
        },
        "by_person": by_person,
        "by_client": by_client,
        # Kod definicji — ta sama konwencja co `/api/insights/board`, żeby front
        # nie zgadywał, którą z trzech definicji placementu ogląda.
        "placements_definition": FIRST_HIRED_PER_CANDIDATE_JOB,
    }
    await cache_set(cache_key, result, ttl_seconds=CACHE_TTL_SECONDS)
    return result
