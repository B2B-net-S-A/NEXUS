"""Kokpit Rady: serie miesiąc × rok dla porównania rok-do-roku.

Układ, który Rada zna z DynaReportera: każda metryka to tabela dwanaście
miesięcy × trzy lata, obok siebie, z deltą i oceną. Ten moduł liczy WYŁĄCZNIE
liczby. Delty, „Ocena" i podsumowanie roczne są czystą arytmetyką na tych
liczbach i mieszkają w widoku — liczenie ich tutaj oznaczałoby, że zmiana
sposobu porównania wymaga deployu backendu, a przy okazji drugą, rozjeżdżającą
się definicję „lepiej" (front i tak musi umieć pokolorować komórkę).

## Trzy rodzaje metryk i dlaczego ich nie wolno mieszać

* **Stan (`stock`)** — MRR, koszt, marża, liczba konsultantów. To ZDJĘCIE na
  konkretny dzień, nie suma za okres. Sumowanie dwunastu miesięcy MRR daje
  liczbę, która nie opisuje niczego (dwunastokrotność stanu), dlatego każda
  metryka niesie `aggregate`, a widok się nim kieruje. W DynaReporterze tego
  pola nie było i wiersz „Suma" pod kolumną procentów pokazywał 874%.
* **Przepływ (`flow`)** — placementy, zejścia, rezygnacje. Liczone w oknie
  miesiąca; sumują się przez rok.
* **Wskaźnik (`ratio`)** — hit ratio, udział top klienta, marża na godzinę.
  Uśredniają się przez rok i NIGDY nie sumują.

## Miesiąc, który jeszcze trwa, nie jest miesiącem słabym

Miesiące w całości przyszłe wracają jako `null` — „nie wydarzyły się" to nie
to samo co „wyszło zero". Miesiąc BIEŻĄCY wraca z realną, ale niepełną
wartością i jest wskazany w `partial_month`; bez tego wrześniowy słupek
czytałby się jak załamanie, a nie jak siedem dni danych. Ta sama pułapka
zabrała kiedyś cały ekran: pierwszego dnia miesiąca DynaReporter pokazywał
same zera i komunikat „Brak danych".

## Pieniądze

Wycena idzie przez `insights_board_money.fold_money`, czyli DOKŁADNIE tę samą
funkcję co kafle kokpitu — kafel „Marża / mc" i komórka „Marża" w tabeli obok
muszą pochodzić z jednego miejsca. Kontrakty ładowane są RAZ na całą odpowiedź
(z `RATE_SCHEDULE_LOADS`, inaczej `MissingGreenlet` → 500 bez CORS), a wycena
per miesiąc odbywa się już w pamięci.

Braki kursu NBP nie kasują kwot po cichu: miesiące dotknięte brakiem wracają
w `degraded.fx.months_affected`, żeby dało się zdegradować komórkę, a nie
całą stronę.
"""

from __future__ import annotations

import calendar
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Optional

from sqlalchemy import or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.services.contract_rates import RATE_SCHEDULE_LOADS, REVENUE_BEARING_STATUSES
from app.services.fx_service import rates_to_pln_by_date
from app.services.insights_board_money import (
    MONTH_LABELS_PL,
    fold_money,
    margin_per_hour,
    money,
    ratio,
    running_on,
)
from app.services.metric_definitions import (
    CLOSED_JOBS_WITH_PLACEMENT,
    FIRST_HIRED_PER_CANDIDATE_JOB,
)

# Ile lat naraz. Trzy to układ z DynaReportera (bieżący + dwa wstecz) i zarazem
# sufit kosztu: każdy rok to dwanaście wycen wszystkich żywych kontraktów.
DEFAULT_YEARS = 3
MAX_YEARS = 5

# Powody zejścia po stronie KONTRAKTORA — podzbiór „rezygnacji" wewnątrz zejść.
# `poached_by_client` świadomie POZA: to klient zabiera człowieka, czyli inne
# zjawisko i inny wniosek dla zarządu, choć skutek dla nas ten sam.
# `performance_issue` i `contract_breach` też nie: tam rozstanie jest decyzją
# jednej ze stron o jakości pracy, nie rezygnacją.
RESIGNATION_REASONS = frozenset(
    {
        ContractTerminationReason.consultant_resigned,
        ContractTerminationReason.better_offer,
        ContractTerminationReason.personal_reasons,
    }
)

# Ilu klientów wymieniamy w rozbiciu miesiąca. Reszta ląduje w „pozostali",
# z liczbą — obcięcie bez reszty zamieniłoby sumę wiersza w liczbę mniejszą
# niż placementy tego samego miesiąca w wierszu wyżej.
CLIENTS_PER_MONTH = 8

CONTRACTOR_DEPARTURE = "ended_contracts_by_effective_end_date"
CONTRACTOR_RESIGNATION = "ended_contracts_with_contractor_side_reason"
MARGIN_PER_BILLABLE_HOUR = "margin_per_billable_hour_known_units_only"
TOP_CLIENT_SHARE = "top_client_share_of_monthly_placements"
DISTINCT_CLIENTS_WITH_PLACEMENT = "distinct_clients_with_at_least_one_placement"


@dataclass(frozen=True)
class _MonthSlot:
    """Jeden miesiąc siatki: gdzie leży i czy w ogóle się wydarzył."""

    year: int
    month: int
    # Dzień wyceny stanu: ostatni dzień miesiąca, a dla miesiąca trwającego —
    # dzisiaj. Wycena na przyszłość udawałaby wiedzę o kontraktach, które do
    # tego czasu mogą się skończyć.
    asof: Optional[date]
    future: bool
    partial: bool


def _month_slots(years: list[int], today: date) -> list:
    slots = []
    for year in years:
        for month in range(1, 13):
            start = date(year, month, 1)
            last = date(year, month, calendar.monthrange(year, month)[1])
            future = start > today
            partial = start <= today <= last and last > today
            slots.append(
                _MonthSlot(
                    year=year,
                    month=month,
                    asof=None if future else min(last, today),
                    future=future,
                    partial=partial,
                )
            )
    return slots


def _empty_series(years: list[int]) -> dict:
    return {str(y): [None] * 12 for y in years}


async def _placements_by_month_client(db: AsyncSession, span_start, span_end) -> dict:
    """Placementy (D2) w rozbiciu miesiąc × klient.

    Klucz to `analytics_first_milestones` — widok zdeduplikowany w definicji
    (`rn = 1` per kandydat × oferta × etap), więc powrót na etap nie liczy się
    drugi raz. LEFT JOIN do ofert i klientów: placement bez powiązanego klienta
    ma zostać policzony w sumie miesiąca, tylko bez nazwy — wycięcie go
    rozjechałoby sumę z wierszem „Liczba placementów" wyżej.
    """
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT
                      date_part('year', fm.first_reached_at
                        AT TIME ZONE 'Europe/Warsaw')::int  AS yr,
                      date_part('month', fm.first_reached_at
                        AT TIME ZONE 'Europe/Warsaw')::int  AS mo,
                      c.name                                 AS client_name,
                      count(*)                               AS cnt
                    FROM analytics_first_milestones fm
                    LEFT JOIN jobs j   ON j.id = fm.job_id
                    LEFT JOIN clients c ON c.id = j.client_id
                    WHERE fm.stage::text = 'hired'
                      AND fm.first_reached_at >= :start
                      AND fm.first_reached_at < :end
                    GROUP BY 1, 2, 3
                    """
                ),
                {"start": span_start, "end": span_end},
            )
        )
        .mappings()
        .all()
    )
    out: dict = defaultdict(list)
    for row in rows:
        out[(int(row["yr"]), int(row["mo"]))].append(
            (row["client_name"], int(row["cnt"]))
        )
    return out


async def _jobs_closed_by_month(db: AsyncSession, span_start, span_end) -> dict:
    """Rekrutacje ZAMKNIĘTE w miesiącu i ile z nich miało placement.

    Data zamknięcia jest w oknie, a zatrudnienie liczy się kiedykolwiek —
    ofertę zamkniętą w lipcu zwykle obsadzono w czerwcu, więc dopięcie
    zatrudnienia do okna wycięłoby większość trafień i zaniżyło wskaźnik.
    """
    rows = (
        (
            await db.execute(
                text(
                    """
                    SELECT
                      date_part('year', j.closed_at
                        AT TIME ZONE 'Europe/Warsaw')::int  AS yr,
                      date_part('month', j.closed_at
                        AT TIME ZONE 'Europe/Warsaw')::int  AS mo,
                      count(*)                                AS closed_total,
                      count(*) FILTER (WHERE filled.job_id IS NOT NULL)
                        AS closed_with_placement
                    FROM jobs j
                    LEFT JOIN LATERAL (
                      SELECT fm.job_id
                      FROM analytics_first_milestones fm
                      WHERE fm.job_id = j.id AND fm.stage::text = 'hired'
                      LIMIT 1
                    ) filled ON TRUE
                    WHERE j.status::text = 'closed'
                      AND j.closed_at >= :start
                      AND j.closed_at < :end
                    GROUP BY 1, 2
                    """
                ),
                {"start": span_start, "end": span_end},
            )
        )
        .mappings()
        .all()
    )
    return {
        (int(r["yr"]), int(r["mo"])): (
            int(r["closed_total"] or 0),
            int(r["closed_with_placement"] or 0),
        )
        for r in rows
    }


def _departures_by_month(contracts) -> tuple:
    """Zejścia i rezygnacje z WCZYTANYCH kontraktów, bez drugiego zapytania.

    Data zejścia to `COALESCE(terminated_at, end_date)` — ta sama definicja,
    której używa `contract_analytics.termination_analysis`; wypowiedzenie przed
    czasem ma się liczyć w swoim miesiącu, nie w pierwotnym terminie.
    """
    departures: dict = defaultdict(int)
    resignations: dict = defaultdict(int)
    unspecified = 0
    for contract in contracts:
        if contract.status != ContractStatus.ended:
            continue
        when = contract.terminated_at or contract.end_date
        if when is None:
            continue
        key = (when.year, when.month)
        departures[key] += 1
        if contract.termination_reason is None:
            unspecified += 1
        elif contract.termination_reason in RESIGNATION_REASONS:
            resignations[key] += 1
    return departures, resignations, unspecified


async def compute_board_yoy(db: AsyncSession, years: list[int], today: date) -> dict:
    """Serie miesiąc × rok dla wszystkich metryk kokpitu Rady."""
    span_start = date(min(years), 1, 1)
    span_end_exclusive = date(max(years) + 1, 1, 1)
    slots = _month_slots(years, today)
    valued = [s for s in slots if s.asof is not None]

    # ── Kontrakty: JEDEN odczyt na całą odpowiedź ───────────────────────────
    contracts = (
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.status.in_(REVENUE_BEARING_STATUSES),
                    Contract.start_date.is_not(None),
                    Contract.start_date < span_end_exclusive,
                    or_(Contract.end_date.is_(None), Contract.end_date >= span_start),
                )
                .options(selectinload(Contract.candidate), *RATE_SCHEDULE_LOADS)
            )
        )
        .scalars()
        .all()
    )

    currencies = {
        currency
        for c in contracts
        for currency in (
            c.resolved_rate_client_currency,
            c.resolved_rate_candidate_currency,
        )
    }
    # Kursy na WSZYSTKIE dni wyceny naraz — jedno zapytanie zamiast N×M.
    rates_by_date = await rates_to_pln_by_date(db, {s.asof: currencies for s in valued})

    placements_map = await _placements_by_month_client(
        db, span_start, span_end_exclusive
    )
    jobs_map = await _jobs_closed_by_month(db, span_start, span_end_exclusive)
    departures, resignations, unspecified_reason = _departures_by_month(contracts)

    # ── Serie ────────────────────────────────────────────────────────────────
    series = {
        key: _empty_series(years)
        for key in (
            "revenue_monthly_pln",
            "consultant_cost_monthly_pln",
            "margin_monthly_pln",
            "margin_pct",
            "consultants",
            "departures",
            "resignations",
            "placements",
            "unique_clients",
            "top_client_share_pct",
            "margin_per_hour_pln",
            "hit_ratio_pct",
            "jobs_closed",
        )
    }
    by_client: dict = {str(y): [None] * 12 for y in years}
    missing_currencies: set = set()
    months_degraded: list = []
    months_without_hours = 0
    partial_month: Optional[dict] = None

    for slot in slots:
        y, idx = str(slot.year), slot.month - 1
        if slot.partial:
            partial_month = {"year": slot.year, "month": slot.month}
        if slot.future:
            # Wszystko zostaje `None`: miesiąc się nie wydarzył.
            continue

        # — przepływy —
        client_rows = sorted(
            placements_map.get((slot.year, slot.month), []),
            key=lambda kv: (-kv[1], (kv[0] or "")),
        )
        total_placements = sum(cnt for _, cnt in client_rows)
        series["placements"][y][idx] = total_placements
        series["departures"][y][idx] = departures.get((slot.year, slot.month), 0)
        series["resignations"][y][idx] = resignations.get((slot.year, slot.month), 0)

        named = [(nm, cnt) for nm, cnt in client_rows if nm]
        series["unique_clients"][y][idx] = len(named)
        series["top_client_share_pct"][y][idx] = (
            ratio(named[0][1], total_placements) if named else None
        )
        head = named[:CLIENTS_PER_MONTH]
        rest = sum(cnt for _, cnt in named[CLIENTS_PER_MONTH:])
        unnamed = total_placements - sum(cnt for _, cnt in named)
        by_client[y][idx] = {
            "clients": [{"name": nm, "count": cnt} for nm, cnt in head],
            # Reszta jedzie jako LICZBA, nie znika: suma wiersza musi zgadzać
            # się z „Liczbą placementów" w tabeli wyżej.
            "other_count": rest,
            "unassigned_count": unnamed,
            "total": total_placements,
        }

        closed_total, closed_filled = jobs_map.get((slot.year, slot.month), (0, 0))
        series["jobs_closed"][y][idx] = closed_total
        series["hit_ratio_pct"][y][idx] = ratio(closed_filled, closed_total)

        # — stan (pieniądze i ludzie) —
        assert slot.asof is not None
        fold = fold_money(
            running_on(contracts, slot.asof),
            slot.asof,
            rates_by_date.get(slot.asof, {}),
        )
        missing_currencies |= set(fold.missing_currencies)
        if not fold.complete:
            months_degraded.append(f"{slot.year}-{slot.month:02d}")
        if fold.contracts_without_hours:
            months_without_hours += 1
        series["revenue_monthly_pln"][y][idx] = money(fold.revenue)
        series["consultant_cost_monthly_pln"][y][idx] = money(fold.cost)
        series["margin_monthly_pln"][y][idx] = money(fold.margin)
        series["margin_pct"][y][idx] = ratio(fold.margin, fold.revenue)
        series["consultants"][y][idx] = fold.consultants
        series["margin_per_hour_pln"][y][idx] = margin_per_hour(fold)

    metrics = [
        _metric(
            "revenue_monthly_pln",
            "finanse",
            "Przychody (MRR)",
            "pln",
            "avg",
            series,
            note="Zdjęcie stanu na ostatni dzień miesiąca — nie suma faktur.",
        ),
        _metric(
            "consultant_cost_monthly_pln",
            "finanse",
            "Koszty konsultantów",
            "pln",
            "avg",
            series,
            lower_is_better=True,
        ),
        _metric("margin_monthly_pln", "finanse", "Marża", "pln", "avg", series),
        _metric("margin_pct", "finanse", "Marża %", "pct", "avg", series),
        _metric("consultants", "hr", "Liczba konsultantów", "count", "avg", series),
        _metric(
            "departures",
            "hr",
            "Liczba zejść",
            "count",
            "sum",
            series,
            lower_is_better=True,
            definition=CONTRACTOR_DEPARTURE,
        ),
        _metric(
            "resignations",
            "hr",
            "Liczba rezygnacji",
            "count",
            "sum",
            series,
            lower_is_better=True,
            definition=CONTRACTOR_RESIGNATION,
            note="Podzbiór zejść: rezygnacja, lepsza oferta, powody osobiste.",
        ),
        _metric(
            "placements",
            "hr",
            "Liczba placementów",
            "count",
            "sum",
            series,
            definition=FIRST_HIRED_PER_CANDIDATE_JOB,
        ),
        _metric(
            "unique_clients",
            "dywersyfikacja",
            "Liczba unikalnych klientów",
            "count",
            "avg",
            series,
            definition=DISTINCT_CLIENTS_WITH_PLACEMENT,
        ),
        _metric(
            "top_client_share_pct",
            "dywersyfikacja",
            "Udział top klienta",
            "pct",
            "avg",
            series,
            lower_is_better=True,
            definition=TOP_CLIENT_SHARE,
            note="Im niżej, tym mniejsza koncentracja na jednym kliencie.",
        ),
        _metric(
            "margin_per_hour_pln",
            "operacyjne",
            "Średnia marża na konsultancie (PLN/h)",
            "pln",
            "avg",
            series,
            definition=MARGIN_PER_BILLABLE_HOUR,
            note=(
                "Ważona, wyłącznie z kontraktów o znanej liczbie godzin "
                "(godzinowe i dzienne); ryczałt miesięczny nie niesie godzin."
            ),
        ),
        _metric(
            "hit_ratio_pct",
            "operacyjne",
            "Hit ratio",
            "pct",
            "avg",
            series,
            definition=CLOSED_JOBS_WITH_PLACEMENT,
        ),
    ]

    degraded: Optional[dict] = None
    reasons: list = []
    parts: list = []
    if missing_currencies:
        reasons.append("fx_missing")
        parts.append(
            "Brak kursu NBP dla walut: "
            + ", ".join(sorted(missing_currencies))
            + " — kwoty w tych walutach są POMINIĘTE w dotkniętych miesiącach."
        )
    if unspecified_reason:
        reasons.append("termination_reason_missing")
        parts.append(
            f"{unspecified_reason} zakończonych kontraktów bez powodu — "
            "liczą się do zejść, ale nie mogą trafić do rezygnacji."
        )
    if months_without_hours:
        reasons.append("hours_unknown")
        parts.append(
            f"W {months_without_hours} miesiącach część kontraktów rozliczana "
            "jest ryczałtem miesięcznym — nie wchodzą do marży na godzinę."
        )
    if reasons:
        degraded = {
            "reasons": reasons,
            "fx": {
                "currencies": sorted(missing_currencies),
                "months_affected": months_degraded,
            },
            "contracts_without_termination_reason": unspecified_reason,
            "message": " ".join(parts),
        }

    return {
        "years": years,
        "asof": today.isoformat(),
        "partial_month": partial_month,
        "month_labels": list(MONTH_LABELS_PL),
        "metrics": metrics,
        "placements_by_client": by_client,
        "degraded": degraded,
    }


def _metric(
    key: str,
    group: str,
    label: str,
    unit: str,
    aggregate: str,
    series: dict,
    *,
    lower_is_better: bool = False,
    definition: Optional[str] = None,
    note: Optional[str] = None,
) -> dict:
    """Metryka razem z instrukcją, jak ją czytać.

    `aggregate` jedzie w odpowiedzi, bo bez niego widok musiałby mieć własną
    listę „co się sumuje, a co uśrednia" — czyli drugie lustro tej wiedzy,
    rozjeżdżające się przy pierwszej nowej metryce. `lower_is_better` rządzi
    kolumną „Ocena": dla zejść i kosztów wzrost jest złą wiadomością, a bez
    tej flagi zielona strzałka w górę mówiłaby coś odwrotnego do prawdy.
    """
    return {
        "key": key,
        "group": group,
        "label": label,
        "unit": unit,
        "aggregate": aggregate,
        "lower_is_better": lower_is_better,
        "definition": definition,
        "note": note,
        "series": series[key],
    }


def resolve_years(end_year: Optional[int], count: int, today: date) -> list:
    """Lata do policzenia — rosnąco, kończąc na ``end_year`` (domyślnie bieżący)."""
    last = end_year or today.year
    return [last - i for i in range(count - 1, -1, -1)]


__all__ = [
    "DEFAULT_YEARS",
    "MAX_YEARS",
    "compute_board_yoy",
    "resolve_years",
]
