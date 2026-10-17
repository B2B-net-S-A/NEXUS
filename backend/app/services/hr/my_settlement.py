"""„Mój czas → Premie i stawka” — premie „w drodze” i moje rozliczenie (etap 2).

Tylko o sobie: wołający podaje własne ``user_id`` (trasy ``/api/hr/payroll/me…``).
Nic tu nie zapisuje do bazy.

**Prognoza premii (D2).** Podpisany kontrakt przed startem ma status
``active`` (``contract_lifecycle.activate_without_revenue_gate`` aktywuje go
przy podpisie, lista kontraktów liczy takie jako „Aktywne” z przyszłym
startem). Automat zakłada propozycję, gdy zna marżę — a stawka klienta
przychodzi zwykle dopiero z zamówieniem, więc do tego czasu premii nie widać.
Prognoza bierze te same kontrakty co automat (aktywne albo kończące się, nie
„powrót po przerwie”, start w oknie automatu, przed terminem premii i bez
końca przed terminem) i te same reguły: odbiorcy i kwoty z
``placement_bonuses.placement_targets``, termin ``bonus_rules.eligible_date``,
postęp ``bonus_rules.business_days_elapsed`` (kalendarz firmy z dniami
wolnymi). Pozycja, dla której automat już założył wiersz premii (każdy stan),
nie trafia do prognozy — jest w premiach.
Kwota to szacunek; bez stawek albo kursu NBP — ``amount = None`` z powodem.

**Rozliczenie (D3).** Miesiąc zamknięty = zamrożone ``payroll_lines`` osoby
(godziny, stawka, kwota za godziny, premie, razem), ``final = True``. Miesiąc
otwarty = szacunek tą samą regułą co raport płac (``payroll_report``): stawka
obowiązująca 1. dnia miesiąca, premie przyznane z okresem w tym miesiącu,
a godziny z „Mojego miesiąca” — suma wpisów timesheetu (zaakceptowanego albo
w toku: szkic i wysłany liczą się tak, jak są wpisane). Płace przy zamknięciu
biorą tylko zaakceptowane, więc szacunek zmienia się do zamknięcia.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contract import Contract, ContractStatus
from app.models.hr_payroll import HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_time import Timesheet, TimesheetEntry
from app.models.job import Job
from app.models.team_structure import DeliveryLeadClientAssignment
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.hr import payroll_rates
from app.services.hr import placement_bonuses as placements
from app.services.hr.bonus_rules import (
    BonusRules,
    business_days_elapsed,
    eligible_date,
    load_bonus_calendar,
    load_rules,
)
from app.services.hr.payroll_bonuses import CATEGORY_LABELS
from app.services.hr.payroll_periods import label, month_start
from app.services.hr.payroll_report import money

ZERO = Decimal("0")
#: Kontrakty, które jeszcze mogą być przed terminem premii (21 dni roboczych
#: to najwyżej ~5 tygodni z świętami) — zgrubny filtr SQL, dokładnie liczy
#: ``eligible_date``.
FORECAST_WINDOW_DAYS = 60
FORECAST_STATUSES = (ContractStatus.active, ContractStatus.ending)


# ── Prognoza premii „w drodze” ────────────────────────────────────────────────


def _relevance_clause(user_id: int, dl_ids: set[int], client_ids: set[int]) -> Any:
    """Kontrakty, przy których osoba MOŻE być odbiorcą (nadzbiór — decyduje
    ``placement_targets``): rekruter albo DL rekrutacji, DL klienta
    (zapasowo, gdy rekrutacja nie ma DL), DL, za którym idzie dodatkowa premia."""

    clauses = [Job.recruiter_id == user_id, Job.delivery_lead_id.in_(sorted(dl_ids))]
    if client_ids:
        clauses.append(Contract.client_id.in_(sorted(client_ids)))
    return or_(*clauses)


async def bonus_forecast(
    db: AsyncSession,
    *,
    user_id: int,
    today: date,
    rules: Optional[BonusRules] = None,
) -> list[dict[str, Any]]:
    """Premie z placementów, które osoba dostałaby według reguł automatu,
    a których automat jeszcze nie założył (najbliższy termin pierwszy)."""

    rules = rules or await load_rules(db)
    dl_ids = {user_id} | {
        rule.dl_user_id for rule in rules.extra_dl if rule.recipient_user_id == user_id
    }
    client_ids = set(
        await db.scalars(
            select(DeliveryLeadClientAssignment.client_id).where(
                DeliveryLeadClientAssignment.delivery_lead_user_id.in_(sorted(dl_ids))
            )
        )
    )
    floor = max(
        placements.automation_floor(rules, today),
        today - timedelta(days=FORECAST_WINDOW_DAYS),
    )
    contracts = list(
        await db.scalars(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .outerjoin(Job, Job.id == Contract.job_id)
            .where(
                Contract.status.in_(FORECAST_STATUSES),
                Contract.start_date.is_not(None),
                Contract.start_date >= floor,
                Contract.returned_from_contract_id.is_(None),
                _relevance_clause(user_id, dl_ids, client_ids),
            )
            .order_by(Contract.start_date, Contract.id)
        )
    )
    if not contracts:
        return []
    existing = set(
        await db.scalars(
            select(HrBonus.source_key).where(
                HrBonus.source == placements.SOURCE,
                HrBonus.contract_id.in_([c.id for c in contracts]),
            )
        )
    )
    # Hurtem przed pętlą: rekrutacje, DL klientów, nazwy i kalendarz firmy.
    context = await placements.load_context(db, contracts)
    first_start, last_start = contracts[0].start_date, contracts[-1].start_date
    assert first_start is not None and last_start is not None
    calendar = await load_bonus_calendar(db, first_start, max(last_start, today), rules)
    items: list[dict[str, Any]] = []
    for contract in contracts:
        start = contract.start_date
        assert start is not None
        eligible_on = eligible_date(start, rules, calendar=calendar)
        if eligible_on <= today or placements.ends_before_deadline(
            contract, eligible_on
        ):
            continue
        dl_id, recruiter_id, _source = context.people(contract)
        candidates = {
            role: target
            for role, target in placements.placement_targets(
                # Odbiorców liczymy najpierw bez kwoty: marżę (kurs NBP) tylko,
                # gdy ta osoba w ogóle coś dostaje.
                None,
                dl_id,
                recruiter_id,
                rules,
            ).items()
            if target.recipient_user_id == user_id
            and placements.source_key(contract.id, role) not in existing
        }
        if not candidates:
            continue
        margin = await placements.contract_margin(db, contract, start)
        targets = placements.placement_targets(
            margin.per_hour, dl_id, recruiter_id, rules
        )
        candidate_name, client_name = context.names(contract)
        for role in candidates:
            target = targets.get(role)
            if target is None or target.recipient_user_id != user_id:
                continue  # znana marża i brak premii (np. marża ujemna)
            items.append(
                {
                    "key": placements.source_key(contract.id, role),
                    "contract_id": contract.id,
                    "role": role,
                    "category": target.category,
                    "category_label": CATEGORY_LABELS.get(
                        target.category, target.category
                    ),
                    "description": placements.placement_description(
                        role, candidate_name, client_name
                    ),
                    "amount": None
                    if target.amount is None
                    else str(money(target.amount)),
                    "currency": rules.currency,
                    "amount_missing_reason": margin.reason
                    if target.amount is None
                    else None,
                    "start_date": start.isoformat(),
                    "started": start <= today,
                    "eligible_on": eligible_on.isoformat(),
                    "business_days_elapsed": business_days_elapsed(
                        start, today, calendar=calendar
                    ),
                    "business_days_required": rules.eligible_business_days,
                }
            )
    items.sort(key=lambda item: (item["eligible_on"], item["key"]))
    return items


# ── Moje rozliczenie ──────────────────────────────────────────────────────────


def _line_payload(
    *,
    currency: str,
    hourly_rate: Optional[Decimal],
    hours_amount: Optional[Decimal],
    bonus_total: Decimal,
    total: Decimal,
) -> dict[str, Any]:
    return {
        "currency": currency,
        "hourly_rate": None if hourly_rate is None else str(hourly_rate),
        "hours_amount": None if hours_amount is None else str(hours_amount),
        "bonus_total": str(bonus_total),
        "total": str(total),
    }


async def _closed_lines(
    db: AsyncSession, user_id: int, year: int
) -> dict[int, list[PayrollLine]]:
    rows = await db.execute(
        select(PayrollPeriod.month, PayrollLine)
        .join(PayrollLine, PayrollLine.period_id == PayrollPeriod.id)
        .where(
            PayrollPeriod.year == year,
            PayrollPeriod.status == "closed",
            PayrollLine.user_id == user_id,
        )
        .order_by(PayrollPeriod.month, PayrollLine.currency)
    )
    out: dict[int, list[PayrollLine]] = defaultdict(list)
    for month, line in rows.all():
        out[int(month)].append(line)
    return out


async def _closed_months(db: AsyncSession, year: int) -> set[int]:
    return {
        int(month)
        for month in await db.scalars(
            select(PayrollPeriod.month).where(
                PayrollPeriod.year == year, PayrollPeriod.status == "closed"
            )
        )
    }


async def _timesheets(
    db: AsyncSession, user_id: int, year: int
) -> dict[int, tuple[str, Decimal]]:
    """Status i suma wpisów timesheetu per miesiąc (jak archiwum „Mojego miesiąca”)."""

    rows = await db.execute(
        select(
            Timesheet.month,
            Timesheet.status,
            func.coalesce(func.sum(TimesheetEntry.hours), 0),
        )
        .outerjoin(TimesheetEntry, TimesheetEntry.timesheet_id == Timesheet.id)
        .where(Timesheet.user_id == user_id, Timesheet.year == year)
        .group_by(Timesheet.id)
    )
    return {
        int(month): (str(status), Decimal(total)) for month, status, total in rows.all()
    }


async def _assigned_bonuses(
    db: AsyncSession, user_id: int, year: int
) -> dict[int, dict[str, Decimal]]:
    rows = await db.execute(
        select(HrBonus.period_month, HrBonus.currency, func.sum(HrBonus.amount))
        .where(
            HrBonus.recipient_user_id == user_id,
            HrBonus.period_year == year,
            HrBonus.status == "assigned",
        )
        .group_by(HrBonus.period_month, HrBonus.currency)
    )
    out: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for month, currency, total in rows.all():
        out[int(month)][str(currency)] = Decimal(total)
    return out


def _frozen_month(year: int, month: int, lines: list[PayrollLine]) -> dict[str, Any]:
    head = next((line for line in lines if line.hourly_rate is not None), lines[0])
    return {
        "year": year,
        "month": month,
        "label": label(year, month),
        "final": True,
        "hours": str(head.hours),
        "hours_source": "frozen",
        "timesheet_status": head.timesheet_status,
        "rate_missing": all(line.hourly_rate is None for line in lines)
        and head.hours > 0,
        "lines": [
            _line_payload(
                currency=line.currency,
                hourly_rate=line.hourly_rate,
                hours_amount=line.hours_amount,
                bonus_total=Decimal(line.bonus_total),
                total=Decimal(line.total),
            )
            for line in lines
        ],
    }


def _estimate_month(
    year: int,
    month: int,
    *,
    timesheet: Optional[tuple[str, Decimal]],
    rate: Any,
    bonuses: dict[str, Decimal],
) -> dict[str, Any]:
    """Szacunek miesiąca regułą raportu płac (``payroll_report.compute_live``)."""

    status, hours = timesheet if timesheet else (None, ZERO)
    currencies = set(bonuses)
    if rate is not None:
        currencies.add(rate.currency)
    lines = []
    for currency in sorted(currencies):
        bonus_total = money(bonuses.get(currency, ZERO))
        hourly: Optional[Decimal] = None
        hours_amount: Optional[Decimal] = None
        if rate is not None and rate.currency == currency:
            hourly = Decimal(rate.hourly_rate)
            hours_amount = money(hours * hourly)
        lines.append(
            _line_payload(
                currency=currency,
                hourly_rate=hourly,
                hours_amount=hours_amount,
                bonus_total=bonus_total,
                total=money((hours_amount or ZERO) + bonus_total),
            )
        )
    return {
        "year": year,
        "month": month,
        "label": label(year, month),
        "final": False,
        "hours": str(hours),
        "hours_source": "none"
        if status is None
        else ("approved" if status == "approved" else "entered"),
        "timesheet_status": status,
        "rate_missing": rate is None and hours > 0,
        "lines": lines,
    }


async def settlement(
    db: AsyncSession, *, user_id: int, year: int, today: date
) -> dict[str, Any]:
    """Miesiące roku od najnowszego: zamknięte z linii płac, otwarte jako szacunek.

    Miesiąc otwarty bez godzin i bez premii pomijamy — poza bieżącym, który
    zawsze jest na liście (dopóki trwa, ma się z czego uzupełniać).
    """

    last = 12 if year < today.year else (today.month if year == today.year else 0)
    closed = await _closed_months(db, year)
    frozen = await _closed_lines(db, user_id, year)
    timesheets = await _timesheets(db, user_id, year)
    bonuses = await _assigned_bonuses(db, user_id, year)
    rates = await payroll_rates.history(db, user_id)

    months: list[dict[str, Any]] = []
    paid: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for month in range(last, 0, -1):
        if month in closed:
            lines = frozen.get(month)
            if not lines:
                continue  # osoby nie było na liście płac tego miesiąca
            months.append(_frozen_month(year, month, lines))
            for line in lines:
                paid[line.currency] += Decimal(line.bonus_total)
            continue
        timesheet = timesheets.get(month)
        month_bonuses = bonuses.get(month, {})
        current = (year, month) == (today.year, today.month)
        if (
            not current
            and not month_bonuses
            and (timesheet is None or not timesheet[1])
        ):
            continue
        months.append(
            _estimate_month(
                year,
                month,
                timesheet=timesheet,
                rate=payroll_rates.rate_on(rates, month_start(year, month)),
                bonuses=month_bonuses,
            )
        )
    return {
        "year": year,
        "months": months,
        "bonuses_paid": {
            currency: str(money(total)) for currency, total in sorted(paid.items())
        },
    }


__all__ = ["FORECAST_WINDOW_DAYS", "bonus_forecast", "settlement"]
