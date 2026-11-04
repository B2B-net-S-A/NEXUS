"""Raport miesiąca płac: godziny zatwierdzone × stawka + premie, per waluta.

Dopóki miesiąc jest otwarty, raport liczy się z danych przy każdym odczycie;
po zamknięciu czyta zamrożone ``payroll_lines``.

Lista osób:

* osoby z kartoteką zatrudnione w miesiącu (start nie po końcu miesiąca,
  ostatni dzień nie przed początkiem; bez dat decyduje status ≠ ``exited``),
* plus każdy, kto ma w miesiącu zatwierdzone godziny albo przyznaną premię
  (premia po odejściu nie może zniknąć z wypłaty).

Konsultanci B2B u klientów nie mają kartotek, więc na listę nie trafiają —
Compass dokładał do zakładki „all” rolę ``consultant``.

Osoba na zleceniu ze stawką obowiązującą w miesiącu niższą niż minimum roku
tego miesiąca (``payroll_rates.mandate_minimum_shortfall`` — ta sama reguła co
przy zapisie stawki) ma ``minimum_rate``; ``minimum_rate_warnings`` robi z tego
ostrzeżenie przed zamknięciem (bez stawek osób).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_payroll import EmployeeRate, HrBonus, PayrollLine, PayrollPeriod
from app.models.hr_profile import EmployeeProfile
from app.models.user import User
from app.services.hr import payroll_leave_bridge, payroll_rates, payroll_time_bridge
from app.services.hr.payroll_periods import get_period, month_end, month_start
from app.services.hr_foundation_schema import EmploymentStatus

ZERO = Decimal("0")
CENT = Decimal("0.01")


def money(value: Decimal) -> Decimal:
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


@dataclass(frozen=True)
class CurrencyLine:
    currency: str
    hourly_rate: Optional[Decimal]
    hours_amount: Optional[Decimal]
    bonus_total: Decimal
    total: Decimal


@dataclass(frozen=True)
class PersonPayroll:
    user_id: int
    name: str
    employment_type: Optional[str]
    manager_user_id: Optional[int]
    timesheet_required: bool
    timesheet_status: Optional[str]
    hours: Decimal
    overtime_hours: Decimal
    paid_leave_days: Decimal
    other_leave_days: Decimal
    rate_missing: bool
    lines: tuple[CurrencyLine, ...]
    #: Minimum roku miesiąca, gdy stawka osoby na zleceniu jest od niego niższa
    #: (ostrzeżenie przed zamknięciem); ``None`` = w porządku albo nie dotyczy.
    minimum_rate: Optional[Decimal] = None


@dataclass(frozen=True)
class MonthReport:
    year: int
    month: int
    status: str
    frozen: bool
    people: list[PersonPayroll] = field(default_factory=list)

    def totals(self) -> dict[str, Decimal]:
        sums: dict[str, Decimal] = defaultdict(lambda: ZERO)
        for person in self.people:
            for line in person.lines:
                sums[line.currency] += line.total
        return {currency: money(total) for currency, total in sorted(sums.items())}


def employed_in_month(profile: EmployeeProfile, year: int, month: int) -> bool:
    start = profile.work_start_date or profile.hired_on
    first, last = month_start(year, month), month_end(year, month)
    if start is not None and start > last:
        return False
    if profile.last_working_day is not None:
        return profile.last_working_day >= first
    if start is None and profile.employment_status == EmploymentStatus.pending:
        return False
    return profile.employment_status != EmploymentStatus.exited


async def _bonus_sums(
    db: AsyncSession, year: int, month: int
) -> dict[int, dict[str, Decimal]]:
    rows = await db.execute(
        select(HrBonus.recipient_user_id, HrBonus.currency, func.sum(HrBonus.amount))
        .where(
            HrBonus.period_year == year,
            HrBonus.period_month == month,
            HrBonus.status == "assigned",
        )
        .group_by(HrBonus.recipient_user_id, HrBonus.currency)
    )
    out: dict[int, dict[str, Decimal]] = defaultdict(dict)
    for user_id, currency, total in rows.all():
        out[int(user_id)][str(currency)] = Decimal(total)
    return out


async def rates_on(db: AsyncSession, day: date) -> dict[int, EmployeeRate]:
    """Stawka obowiązująca w dniu ``day`` per osoba — deterministycznie.

    Dwie stawki obejmujące ten sam dzień (np. zaimportowane z wyłącznym końcem
    Compassa przed poprawką) rozstrzyga najnowsza: ta, która zaczyna się
    później — jak ``payroll_rates.rate_on`` na historii od najnowszej.
    """

    rows = await db.scalars(
        select(EmployeeRate)
        .where(
            EmployeeRate.effective_from <= day,
            (EmployeeRate.effective_to.is_(None)) | (EmployeeRate.effective_to >= day),
        )
        .order_by(
            EmployeeRate.user_id,
            EmployeeRate.effective_from.desc(),
            EmployeeRate.id.desc(),
        )
    )
    found: dict[int, EmployeeRate] = {}
    for rate in rows:
        found.setdefault(rate.user_id, rate)
    return found


async def compute_live(db: AsyncSession, year: int, month: int) -> list[PersonPayroll]:
    first, last = month_start(year, month), month_end(year, month)
    profiles = {
        profile.user_id: (profile, name)
        for profile, name in (
            await db.execute(
                select(EmployeeProfile, User.name).join(
                    User, User.id == EmployeeProfile.user_id
                )
            )
        ).all()
    }
    hours = await payroll_time_bridge.approved_hours(db, year, month)
    statuses = await payroll_time_bridge.timesheet_statuses(db, year, month)
    bonuses = await _bonus_sums(db, year, month)
    rates = await rates_on(db, first)
    minimums = await payroll_rates.load_minimum_rates(db)
    leave = await payroll_leave_bridge.leave_days(db, first, last)

    user_ids = {
        user_id
        for user_id, (profile, _name) in profiles.items()
        if employed_in_month(profile, year, month)
    }
    user_ids |= {uid for uid in hours if uid in profiles}
    user_ids |= set(bonuses)
    missing_names = sorted(uid for uid in user_ids if uid not in profiles)
    extra_names: dict[int, str] = {}
    if missing_names:
        extra_names = {
            int(uid): str(name)
            for uid, name in (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(missing_names))
                )
            ).all()
        }

    people: list[PersonPayroll] = []
    for user_id in user_ids:
        profile, name = profiles.get(user_id, (None, extra_names.get(user_id, "")))
        worked = hours.get(user_id)
        person_hours = worked.hours if worked else ZERO
        overtime = worked.overtime_hours if worked else ZERO
        rate = rates.get(user_id)
        person_bonuses = bonuses.get(user_id, {})
        currencies = set(person_bonuses)
        if rate is not None:
            currencies.add(rate.currency)
        lines: list[CurrencyLine] = []
        for currency in sorted(currencies):
            bonus_total = money(person_bonuses.get(currency, ZERO))
            hourly: Optional[Decimal] = None
            hours_amount: Optional[Decimal] = None
            if rate is not None and rate.currency == currency:
                hourly = Decimal(rate.hourly_rate)
                hours_amount = money(person_hours * hourly)
            lines.append(
                CurrencyLine(
                    currency=currency,
                    hourly_rate=hourly,
                    hours_amount=hours_amount,
                    bonus_total=bonus_total,
                    total=money((hours_amount or ZERO) + bonus_total),
                )
            )
        days = leave.get(user_id)
        employment_type = profile.employment_type if profile else None
        people.append(
            PersonPayroll(
                user_id=user_id,
                name=name,
                employment_type=employment_type,
                manager_user_id=profile.manager_user_id if profile else None,
                timesheet_required=bool(profile.timesheet_required)
                if profile
                else False,
                timesheet_status=statuses.get(user_id),
                hours=person_hours,
                overtime_hours=overtime,
                paid_leave_days=days.paid if days else ZERO,
                other_leave_days=days.other if days else ZERO,
                rate_missing=rate is None and person_hours > 0,
                lines=tuple(lines),
                minimum_rate=payroll_rates.mandate_minimum_shortfall(
                    employment_type=employment_type,
                    hourly_rate=Decimal(rate.hourly_rate),
                    currency=rate.currency,
                    year=year,
                    rates=minimums,
                )
                if rate is not None
                else None,
            )
        )
    people.sort(key=lambda p: (p.name.casefold(), p.user_id))
    return people


def minimum_rate_warnings(
    people: list[PersonPayroll], *, people_limit: int
) -> list[dict[str, Any]]:
    """Ostrzeżenie „stawka poniżej minimum na zleceniu” — imiona, liczba i minimum.

    Stawek osób w komunikacie nie ma (jak w pozostałych ostrzeżeniach); minimum
    to kwota z Ustawień → Płace, jedna dla wszystkich osób miesiąca.
    """

    below = [p for p in people if p.minimum_rate is not None]
    if not below:
        return []
    minimum = max(p.minimum_rate for p in below if p.minimum_rate is not None)
    return [
        {
            "code": "below_minimum_rate",
            "message": (
                f"{len(below)} os. na zleceniu ma stawkę niższą niż minimalna "
                f"w tym miesiącu ({payroll_rates.format_pln(minimum)} zł/h brutto) "
                "— popraw stawkę przed zamknięciem."
            ),
            "count": len(below),
            "people": [{"user_id": p.user_id, "name": p.name} for p in below][
                :people_limit
            ],
        }
    ]


async def frozen_people(db: AsyncSession, period: PayrollPeriod) -> list[PersonPayroll]:
    rows = list(
        await db.scalars(
            select(PayrollLine)
            .where(PayrollLine.period_id == period.id)
            .order_by(PayrollLine.user_id, PayrollLine.currency)
        )
    )
    user_ids = sorted({row.user_id for row in rows})
    managers: dict[int, Optional[int]] = {}
    required: dict[int, bool] = {}
    if user_ids:
        for uid, manager_id, needs in (
            await db.execute(
                select(
                    EmployeeProfile.user_id,
                    EmployeeProfile.manager_user_id,
                    EmployeeProfile.timesheet_required,
                ).where(EmployeeProfile.user_id.in_(user_ids))
            )
        ).all():
            managers[int(uid)] = manager_id
            required[int(uid)] = bool(needs)
    grouped: dict[int, list[PayrollLine]] = defaultdict(list)
    for row in rows:
        grouped[row.user_id].append(row)
    people: list[PersonPayroll] = []
    for user_id, lines in grouped.items():
        # Godziny i dni niesie linia waluty stawki (jak przy zamrażaniu).
        head = next((line for line in lines if line.hourly_rate is not None), lines[0])
        people.append(
            PersonPayroll(
                user_id=user_id,
                name=head.person_name,
                employment_type=head.employment_type,
                manager_user_id=managers.get(user_id),
                timesheet_required=required.get(user_id, False),
                timesheet_status=head.timesheet_status,
                hours=Decimal(head.hours),
                overtime_hours=Decimal(head.overtime_hours),
                paid_leave_days=Decimal(head.paid_leave_days),
                other_leave_days=Decimal(head.other_leave_days),
                rate_missing=all(line.hourly_rate is None for line in lines)
                and head.hours > 0,
                lines=tuple(
                    CurrencyLine(
                        currency=line.currency,
                        hourly_rate=line.hourly_rate,
                        hours_amount=line.hours_amount,
                        bonus_total=Decimal(line.bonus_total),
                        total=Decimal(line.total),
                    )
                    for line in lines
                ),
            )
        )
    people.sort(key=lambda p: (p.name.casefold(), p.user_id))
    return people


def line_rows(period_id: int, people: list[PersonPayroll]) -> list[dict[str, Any]]:
    """Wiersze ``payroll_lines`` do zamrożenia. Osoba bez linii walutowej
    (zero godzin bez stawki i bez premii) dostaje jedną linię PLN z zerami —
    zamknięty miesiąc pokazuje tę samą listę osób co otwarty.
    """

    rows: list[dict[str, Any]] = []
    for person in people:
        lines = person.lines or (
            CurrencyLine(
                currency="PLN",
                hourly_rate=None,
                hours_amount=None,
                bonus_total=ZERO,
                total=ZERO,
            ),
        )
        rate_line = next(
            (line for line in lines if line.hourly_rate is not None), lines[0]
        )
        for line in lines:
            carries_hours = line is rate_line
            rows.append(
                {
                    "period_id": period_id,
                    "user_id": person.user_id,
                    "person_name": person.name[:255] or f"Osoba {person.user_id}",
                    "employment_type": person.employment_type,
                    "currency": line.currency,
                    "hours": person.hours if carries_hours else ZERO,
                    "overtime_hours": person.overtime_hours if carries_hours else ZERO,
                    "hourly_rate": line.hourly_rate,
                    "hours_amount": line.hours_amount,
                    "bonus_total": line.bonus_total,
                    "total": line.total,
                    "paid_leave_days": person.paid_leave_days
                    if carries_hours
                    else ZERO,
                    "other_leave_days": person.other_leave_days
                    if carries_hours
                    else ZERO,
                    "timesheet_status": person.timesheet_status,
                }
            )
    return rows


async def month_report(db: AsyncSession, year: int, month: int) -> MonthReport:
    period = await get_period(db, year, month)
    if period is not None and period.status == "closed":
        return MonthReport(
            year=year,
            month=month,
            status="closed",
            frozen=True,
            people=await frozen_people(db, period),
        )
    return MonthReport(
        year=year,
        month=month,
        status="open",
        frozen=False,
        people=await compute_live(db, year, month),
    )


__all__ = [
    "CurrencyLine",
    "MonthReport",
    "PersonPayroll",
    "compute_live",
    "employed_in_month",
    "frozen_people",
    "line_rows",
    "minimum_rate_warnings",
    "money",
    "month_report",
    "rates_on",
]
