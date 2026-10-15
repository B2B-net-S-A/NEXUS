"""Insights w API integracyjnym v1 — okno ``from``/``to``, miesiące i kontrakty.

Trasy ``api/integrations_v1/insights.py`` liczą tymi samymi funkcjami co
ekran Insights (lejek po etapach, analiza placementów, aktywność zespołu,
Liga Mistrzów, cele zespołu). Tutaj jest tylko to, czego ekran nie ma
w jednym miejscu:

* okno z parametrów ``from``/``to`` (dni kalendarzowe Europe/Warsaw,
  włącznie; bez obu — poprzedni pełny miesiąc, jak domyślny okres Insights)
  pocięte na miesiące kalendarzowe;
* kontrakty w oknie: wejścia, zejścia, rezygnacje, konsultanci i kwoty.
  Kwoty liczy ``insights_board_money.fold_money`` — ta sama funkcja co kokpit
  Rady i tabele rok do roku. Zejście i rezygnacja mają definicje tabel rok do
  roku (``CONTRACTOR_DEPARTURE``, ``CONTRACTOR_RESIGNATION``); wejście to
  kontrakt z datą startu w odcinku (``STARTS_DEFINITION``);
* cele zespołu rekrutacji liczone tak, jak widzi je Head of Recruitment
  (``kpi_goals._team_goals`` na aktywnych rekruterach — sumy, bez osób).

Ewidencja kontraktów jest młodsza niż firma (``docs/claude/finanse-insights``):
liczby z kontraktów sprzed jej startu są zaniżone, a porównanie ich rok do
roku opisuje rozrastanie się ewidencji, nie biznes. Dlatego każdy miesiąc
niesie liczbę wycenionych kontraktów (``priced_contracts``).
"""

import asyncio
import calendar
import hashlib
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Hashable, Iterable, Optional, Sequence

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.periods import Period, PeriodError, resolve_period
from app.core.cache import cache_get, cache_set
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.user import User
from app.services.client_identity import client_display_name
from app.services.contract_rates import RATE_SCHEDULE_LOADS, REVENUE_BEARING_STATUSES
from app.services.fx_service import rates_to_pln_by_date
from app.services.insights_board_money import fold_money, ratio, running_on
from app.services.insights_board_yoy import RESIGNATION_REASONS
from app.services.kpi_goals import GoalsResult, _team_goals
from app.services.kpi_targets import user_kpi_roles_clause

#: Wejście konsultanta: kontrakt (aktywny, kończący się albo zakończony)
#: z datą startu w odcinku. Lustro zejścia (``CONTRACTOR_DEPARTURE``).
STARTS_DEFINITION = "revenue_bearing_contracts_by_start_date"
#: Kwoty: miesięczny przychód/koszt/marża kontraktów wykonywanych w dniu
#: wyceny, ze stawek z harmonogramów (kod jak w kokpicie Rady).
MONEY_BASIS = "mrr_from_rate_schedules"

GOALS_CACHE_TTL_SECONDS = 120


# ── Okno i miesiące ──────────────────────────────────────────────────────────


def resolve_window(
    date_from: Optional[date], date_to: Optional[date], *, today: date
) -> Period:
    """Okno raportu: ``from``–``to`` włącznie albo poprzedni pełny miesiąc.

    Bez obu parametrów — poprzedni pełny miesiąc (domyślny okres Insights:
    pierwszego dnia miesiąca bieżący miesiąc to jeden dzień danych). Jeden
    parametr bez drugiego to błąd, a nie ciche dopowiedzenie drugiego końca.
    Limit długości (366 dni) i zakres lat pilnuje ``resolve_period``.
    """
    if date_from is None and date_to is None:
        return resolve_period("month", offset=-1, anchor=today)
    if date_from is None or date_to is None:
        raise PeriodError(
            "Podaj oba parametry okna: from i to (albo żaden — wtedy poprzedni "
            "pełny miesiąc)."
        )
    return resolve_period("custom", date_from=date_from, date_to=date_to)


def window_days(period: Period) -> tuple[date, date]:
    """Pierwszy i ostatni dzień NALEŻĄCY do okna (``end`` jest poza oknem)."""
    return period.start.date(), (period.end - timedelta(days=1)).date()


@dataclass(frozen=True)
class MonthSlice:
    """Miesiąc kalendarzowy przycięty do okna."""

    month: str
    date_from: date
    date_to: date
    # Odcinek obejmuje cały miesiąc i miesiąc już się skończył — liczby się
    # nie zmienią. Odcinek przycięty oknem albo miesiąc w toku to nie słabszy
    # miesiąc, tylko krótszy.
    complete: bool

    @property
    def period(self) -> Period:
        return resolve_period("custom", date_from=self.date_from, date_to=self.date_to)


def month_slices(period: Period, *, today: date) -> list[MonthSlice]:
    first, last = window_days(period)
    slices: list[MonthSlice] = []
    cursor = first.replace(day=1)
    while cursor <= last:
        month_last = cursor.replace(
            day=calendar.monthrange(cursor.year, cursor.month)[1]
        )
        lo, hi = max(cursor, first), min(month_last, last)
        slices.append(
            MonthSlice(
                month=f"{cursor.year:04d}-{cursor.month:02d}",
                date_from=lo,
                date_to=hi,
                complete=lo == cursor and hi == month_last and month_last < today,
            )
        )
        cursor = month_last + timedelta(days=1)
    return slices


def valuation_day(date_from: date, date_to: date, today: date) -> Optional[date]:
    """Dzień wyceny stanu (konsultanci, kwoty): ostatni dzień odcinka albo dziś.

    Ta sama reguła co kokpit Rady: przyszłości nie wyceniamy, bo wycena na
    przyszły dzień udawałaby wiedzę o kontraktach, które mogą się skończyć.
    Odcinek w całości przyszły nie ma wyceny (``None``) — zero udawałoby wynik.
    """
    if date_from > today:
        return None
    return min(date_to, today)


# ── Kontrakty ────────────────────────────────────────────────────────────────


async def load_contracts(db: AsyncSession, *, first: date, last: date) -> list:
    """Kontrakty nachodzące na okno — ten sam zbiór i te same relacje co tabele
    rok do roku (``RATE_SCHEDULE_LOADS`` obowiązkowe: bez nich wycena robi
    lazy-load w sesji async, czyli ``MissingGreenlet``)."""
    return list(
        (
            await db.execute(
                select(Contract)
                .where(
                    Contract.status.in_(REVENUE_BEARING_STATUSES),
                    Contract.start_date.is_not(None),
                    Contract.start_date <= last,
                    or_(Contract.end_date.is_(None), Contract.end_date >= first),
                )
                .options(selectinload(Contract.candidate), *RATE_SCHEDULE_LOADS)
            )
        )
        .scalars()
        .all()
    )


def departure_day(contract: Any) -> Optional[date]:
    """Dzień zejścia (``CONTRACTOR_DEPARTURE``) — lustro
    ``insights_board_yoy._departures_by_month``: kontrakt zakończony,
    ``COALESCE(end_date, terminated_at)``; ``end_date`` pierwsze, bo
    ``terminated_at`` przeżywa aneks przedłużenia."""
    if contract.status != ContractStatus.ended:
        return None
    return contract.end_date or contract.terminated_at


@dataclass(frozen=True)
class ContractFlows:
    starts: int
    ends: int
    resignations: int


def contract_flows(
    contracts: Iterable[Any], date_from: date, date_to: date
) -> ContractFlows:
    starts = ends = resignations = 0
    for contract in contracts:
        if (
            contract.start_date is not None
            and date_from <= contract.start_date <= date_to
        ):
            starts += 1
        day = departure_day(contract)
        if day is not None and date_from <= day <= date_to:
            ends += 1
            if contract.termination_reason in RESIGNATION_REASONS:
                resignations += 1
    return ContractFlows(starts=starts, ends=ends, resignations=resignations)


@dataclass(frozen=True)
class MoneySnapshot:
    """Stan na dzień wyceny — pola ``fold_money`` bez redakcji kwot."""

    valuation_day: date
    revenue: Decimal
    cost: Decimal
    margin: Decimal
    margin_pct: Optional[float]
    consultants: int
    active_contracts: int
    priced_contracts: int
    contracts_without_cost_leg: int
    contracts_without_revenue_leg: int
    complete: bool
    missing_currencies: tuple[str, ...]


def money_snapshot(contracts: Sequence[Any], on: date, rates: dict) -> MoneySnapshot:
    fold = fold_money(running_on(contracts, on), on, rates)
    return MoneySnapshot(
        valuation_day=on,
        revenue=fold.revenue,
        cost=fold.cost,
        margin=fold.margin,
        # Mianownik = przychód kontraktów ze ZNANĄ marżą (jak kokpit Rady).
        margin_pct=ratio(fold.margin, fold.margin_revenue),
        consultants=fold.consultants,
        active_contracts=fold.active_contracts,
        priced_contracts=fold.priced_contracts,
        contracts_without_cost_leg=fold.without_cost_leg,
        contracts_without_revenue_leg=fold.without_revenue_leg,
        complete=fold.complete,
        missing_currencies=tuple(sorted(c for c in fold.missing_currencies if c)),
    )


@dataclass(frozen=True)
class ContractPart:
    flows: ContractFlows
    money: Optional[MoneySnapshot]


@dataclass(frozen=True)
class ContractReport:
    months: tuple[ContractPart, ...]
    groups: dict
    window_valuation_day: Optional[date]


async def contract_report(
    db: AsyncSession,
    contracts: Sequence[Any],
    slices: Sequence[MonthSlice],
    *,
    today: date,
    group_key: Callable[[Optional[int]], Hashable],
) -> ContractReport:
    """Wejścia, zejścia i wycena per miesiąc oraz per grupa klienta (całe okno).

    ``group_key`` zamienia ``client_id`` kontraktu na klucz grupy — trasa
    zlewa klientów ukrytych i usuniętych w jedną grupę, zanim cokolwiek się
    zsumuje (konsultant liczy się raz w grupie, a nie raz na klienta).
    """
    first, last = slices[0].date_from, slices[-1].date_to
    window_day = valuation_day(first, last, today)
    days = {valuation_day(s.date_from, s.date_to, today) for s in slices}
    days.add(window_day)
    days.discard(None)
    currencies = {
        currency
        for contract in contracts
        for currency in (
            contract.resolved_rate_client_currency,
            contract.resolved_rate_candidate_currency,
        )
    }
    rates_by_date: dict = {}
    if contracts and days:
        rates_by_date = await rates_to_pln_by_date(
            db, {day: currencies for day in days}
        )
    grouped: dict = defaultdict(list)
    for contract in contracts:
        grouped[group_key(contract.client_id)].append(contract)

    def compute() -> ContractReport:
        months = []
        for s in slices:
            day = valuation_day(s.date_from, s.date_to, today)
            months.append(
                ContractPart(
                    flows=contract_flows(contracts, s.date_from, s.date_to),
                    money=(
                        money_snapshot(contracts, day, rates_by_date.get(day, {}))
                        if day is not None
                        else None
                    ),
                )
            )
        groups = {
            key: ContractPart(
                flows=contract_flows(group, first, last),
                money=(
                    money_snapshot(group, window_day, rates_by_date.get(window_day, {}))
                    if window_day is not None
                    else None
                ),
            )
            for key, group in grouped.items()
        }
        return ContractReport(
            months=tuple(months), groups=groups, window_valuation_day=window_day
        )

    # Wycena przez harmonogramy to CPU, nie baza (kontrakty i harmonogramy są
    # już w pamięci) — w wątku, jak tabele rok do roku.
    return await asyncio.to_thread(compute)


# ── Klienci ──────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ClientLabel:
    name: str
    # Klient pokazywany w aplikacji (jak ``job_client_listed_clause``): nie
    # ukryty i nie usunięty. Archiwalny prawdziwy klient zostaje widoczny.
    listed: bool


async def client_labels(db: AsyncSession, ids: Iterable[int]) -> dict[int, ClientLabel]:
    wanted = sorted({int(i) for i in ids if i is not None})
    if not wanted:
        return {}
    rows = (
        await db.execute(
            select(
                Client.id,
                Client.name,
                Client.display_name,
                Client.hidden,
                Client.deleted_at,
            ).where(Client.id.in_(wanted))
        )
    ).all()
    return {
        int(row.id): ClientLabel(
            name=client_display_name(row),
            listed=not row.hidden and row.deleted_at is None,
        )
        for row in rows
    }


# ── Cele zespołu ─────────────────────────────────────────────────────────────


async def company_team_goals(db: AsyncSession, *, now: datetime) -> GoalsResult:
    """Cele zespołu rekrutacji tak, jak widzi je Head of Recruitment.

    Zespół = aktywni rekruterzy (ta sama klauzula ról co zakres pulpitu HoR,
    ``access_scope.resolve_dashboard_scope``); cel = suma celów osób, wynik =
    suma ich pracy (``kpi_goals._team_goals``). Same sumy — bez osób.
    """
    operator_ids = frozenset(
        (
            await db.scalars(
                select(User.id).where(User.is_active.is_(True), user_kpi_roles_clause())
            )
        ).all()
    )
    digest = hashlib.sha256(
        ",".join(str(i) for i in sorted(operator_ids)).encode()
    ).hexdigest()[:16]
    cache_key = f"integrations:v1:insights:goals:team:{digest}"
    cached = await cache_get(cache_key)
    if isinstance(cached, dict):
        return GoalsResult.from_dict(cached)
    result = await _team_goals(db, operator_ids=operator_ids, now=now)
    await cache_set(cache_key, result.as_dict(), ttl_seconds=GOALS_CACHE_TTL_SECONDS)
    return result


__all__ = [
    "MONEY_BASIS",
    "STARTS_DEFINITION",
    "ClientLabel",
    "ContractFlows",
    "ContractPart",
    "ContractReport",
    "MoneySnapshot",
    "MonthSlice",
    "client_labels",
    "company_team_goals",
    "contract_flows",
    "contract_report",
    "departure_day",
    "load_contracts",
    "money_snapshot",
    "month_slices",
    "resolve_window",
    "valuation_day",
    "window_days",
]
