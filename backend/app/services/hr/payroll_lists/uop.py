"""Umowa o pracę z pensją (K7b) — dane z bazy do ``salary.month_pay``.

Pozycja UoP osoby z pensją w ``payroll_salaries`` liczy brutto sama (źródło
``salary``): pensja za przepracowaną część miesiąca, wynagrodzenie chorobowe,
urlopowe za zmienne, ekwiwalent, składniki Płac i premie z zamkniętego
miesiąca. Kwota wpisana przez Płace (K7a) nadal wygrywa ze wszystkim.

Skąd co (decyzje Artura z 16.11.2026):

* **nieobecności** — moduł urlopów NEXUSA (zatwierdzone wnioski), oznaczenie
  L4 (80/100%, zasiłek ZUS od 1. dnia, bez wyczekiwania) z ``payroll_absence_marks``;
* **historia podstaw** — zatwierdzone listy NEXUSA (``basis.k7b.basis``),
  a za miesiące sprzed NEXUSA import z Enovy (``payroll_basis_months``);
  jeden miesiąc ma jedno źródło: lista NEXUSA wygrywa;
* **dni chorobowego w roku** — otwarcie roku (``sick_pay_days``: Enova
  i świadectwa pracy) + zatwierdzone listy NEXUSA wcześniejszych miesięcy roku;
* **ekwiwalent** — umowa kończy się w miesiącu (``last_working_day``): dni
  z puli urlopowej proporcjonalnie do miesięcy pracy w roku, chyba że Płace
  wpiszą dni same (składnik ``equivalent_days``).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_payroll import PayrollPeriod
from app.models.hr_payroll_k7b import (
    PayrollAbsenceMark,
    PayrollBasisMonth,
    PayrollComponent,
    PayrollSalary,
)
from app.models.hr_payroll_lists import PayrollList, PayrollListLine, PayrollYearOpening
from app.models.hr_profile import EmployeeProfile
from app.services.hr import leave_balance
from app.services.hr.payroll_lists import salary as rules
from app.services.hr.payroll_lists.salary import (
    Absence,
    BasisMonth,
    MonthInput,
    PreviousSick,
)

ZERO = Decimal("0")
FAR = date(2100, 12, 31)


@dataclass(frozen=True)
class Loaded:
    """Pensje i składniki okresu — raz na listę."""

    salaries: dict[int, PayrollSalary]
    components: dict[int, dict[str, PayrollComponent]]


async def load_period(db: AsyncSession, period: PayrollPeriod) -> Loaded:
    first, _last = rules.month_bounds(period.year, period.month)
    salaries: dict[int, PayrollSalary] = {}
    for row in await db.scalars(
        select(PayrollSalary)
        .where(
            PayrollSalary.effective_from
            <= rules.month_bounds(period.year, period.month)[1],
            or_(
                PayrollSalary.effective_to.is_(None),
                PayrollSalary.effective_to >= first,
            ),
        )
        .order_by(PayrollSalary.user_id, PayrollSalary.effective_from)
    ):
        # Ostatnia pensja zaczęta najpóźniej 1. dnia miesiąca (pensje od 1. dnia).
        salaries[row.user_id] = row
    components: dict[int, dict[str, PayrollComponent]] = defaultdict(dict)
    for item in await db.scalars(
        select(PayrollComponent).where(PayrollComponent.period_id == period.id)
    ):
        components[item.user_id][item.kind] = item
    return Loaded(salaries=salaries, components=dict(components))


def _dec(raw: Any) -> Decimal:
    try:
        return Decimal(str(raw or "0"))
    except ArithmeticError:
        return ZERO


async def _absences(
    db: AsyncSession, user_id: int, first: date, last: date
) -> tuple[Absence, ...]:
    requests = list(
        await db.scalars(
            select(LeaveRequest)
            .where(
                LeaveRequest.user_id == user_id,
                LeaveRequest.status == "approved",
                LeaveRequest.start_date <= last,
                LeaveRequest.end_date >= first,
            )
            .order_by(LeaveRequest.start_date)
        )
    )
    if not requests:
        return ()
    ids = [item.id for item in requests]
    days: dict[Any, list[tuple[date, Decimal]]] = defaultdict(list)
    for row in await db.scalars(
        select(LeaveRequestDay)
        .where(
            LeaveRequestDay.leave_request_id.in_(ids),
            LeaveRequestDay.active.is_(True),
            LeaveRequestDay.day >= first,
            LeaveRequestDay.day <= last,
        )
        .order_by(LeaveRequestDay.day)
    ):
        days[row.leave_request_id].append((row.day, Decimal(row.fraction)))
    marks = {
        mark.leave_request_id: mark
        for mark in await db.scalars(
            select(PayrollAbsenceMark).where(
                PayrollAbsenceMark.leave_request_id.in_(ids)
            )
        )
    }
    out: list[Absence] = []
    for item in requests:
        mark = marks.get(item.id)
        out.append(
            Absence(
                key=str(item.id),
                leave_type=item.leave_type,
                start=item.start_date,
                end=item.end_date,
                days=tuple(days.get(item.id, ())),
                sick_rate=mark.sick_rate if mark else "80",
                waiting_exempt=bool(mark.waiting_exempt) if mark else False,
            )
        )
    return tuple(out)


async def _nexus_months(
    db: AsyncSession, user_id: int, before: tuple[int, int]
) -> list[tuple[PayrollList, PayrollListLine]]:
    rows = (
        await db.execute(
            select(PayrollList, PayrollListLine)
            .join(PayrollListLine, PayrollListLine.list_id == PayrollList.id)
            .where(
                PayrollList.status == "approved",
                PayrollListLine.user_id == user_id,
                PayrollListLine.kind == "uop",
                or_(
                    PayrollList.year < before[0],
                    and_(PayrollList.year == before[0], PayrollList.month < before[1]),
                ),
            )
            .order_by(PayrollList.year, PayrollList.month, PayrollList.id)
        )
    ).all()
    return [(row[0], row[1]) for row in rows]


def _k7b(line: PayrollListLine) -> dict[str, Any]:
    basis = line.basis or {}
    data = basis.get("k7b")
    return data if isinstance(data, dict) else {}


async def history(
    db: AsyncSession, user_id: int, year: int, month: int
) -> tuple[tuple[BasisMonth, ...], Optional[PreviousSick], int]:
    """Historia podstaw, ostatnia niezdolność z podstawą i dni chorobowego w roku."""

    months: dict[tuple[int, int], BasisMonth] = {}
    for row in await db.scalars(
        select(PayrollBasisMonth).where(PayrollBasisMonth.user_id == user_id)
    ):
        if (row.year, row.month) >= (year, month):
            continue
        months[(row.year, row.month)] = BasisMonth(
            year=row.year,
            month=row.month,
            fixed_paid=Decimal(row.fixed_paid),
            fixed_full=Decimal(row.fixed_full),
            variable=Decimal(row.variable),
            leave_variable=Decimal(row.leave_variable),
            nominal_hours=Decimal(row.nominal_hours),
            worked_hours=Decimal(row.worked_hours),
            paid_hours=Decimal(row.paid_hours),
            full_month=bool(row.full_month),
            source="enova",
        )
    previous: Optional[PreviousSick] = None
    used = 0
    for lst, line in await _nexus_months(db, user_id, (year, month)):
        data = _k7b(line)
        raw_basis = data.get("basis")
        if isinstance(raw_basis, dict):
            # Miesiąc z listą NEXUSA wygrywa z importem z Enovy.
            months[(lst.year, lst.month)] = rules.basis_from_json(raw_basis)
        for part in data.get("sick") or []:
            if not isinstance(part, dict):
                continue
            paid = int(part.get("paid_days") or 0)
            if lst.year == year:
                used += paid
            last_day = part.get("last_day")
            if paid and last_day:
                day = date.fromisoformat(str(last_day))
                if previous is None or day >= previous.last_day:
                    previous = PreviousSick(last_day=day, base=_dec(part.get("base")))
    return tuple(months[key] for key in sorted(months)), previous, used


async def _opening_sick_days(db: AsyncSession, user_id: int, year: int) -> int:
    opening = await db.scalar(
        select(PayrollYearOpening).where(
            PayrollYearOpening.user_id == user_id, PayrollYearOpening.year == year
        )
    )
    if opening is None:
        return 0
    return int(_dec((opening.amounts or {}).get("sick_pay_days")))


async def _equivalent_days(
    db: AsyncSession, user_id: int, year: int, employed_from: date, employed_to: date
) -> tuple[Decimal, bool]:
    rows = await leave_balance.entitlements(db, user_id, [year])
    usage = (await leave_balance.year_usage(db, user_id, [year]))[year]
    row = rows.get(year)
    if row is None or row.entitlement_days is None:
        return ZERO, False
    return rules.unused_leave_days(
        entitlement=Decimal(row.entitlement_days),
        carried_over=Decimal(row.carried_over_days or 0),
        used_before=Decimal(row.used_initial_days or 0),
        used_paid=usage.approved_paid,
        year=year,
        employed_from=employed_from,
        employed_to=employed_to,
    )


async def month_input(
    db: AsyncSession,
    *,
    period: PayrollPeriod,
    user_id: int,
    salary_row: PayrollSalary,
    profile: Optional[EmployeeProfile],
    components: dict[str, PayrollComponent],
    bonuses: Decimal,
) -> tuple[MonthInput, list[str]]:
    """Wejście do ``month_pay`` bez danych osoby (data urodzenia, ubezpieczenie od).

    Zwraca też oznaczenia do pozycji (np. ekwiwalent policzony z puli).
    """

    first, last = rules.month_bounds(period.year, period.month)
    hired = (profile.hired_on or profile.work_start_date) if profile else None
    started = (profile.work_start_date or profile.hired_on) if profile else None
    employed_from = started or salary_row.effective_from
    employed_to = (profile.last_working_day if profile else None) or FAR
    if salary_row.effective_to is not None:
        employed_to = min(employed_to, salary_row.effective_to)
    notes: list[str] = []
    rows, previous, used_nexus = await history(db, user_id, period.year, period.month)
    used = used_nexus + await _opening_sick_days(db, user_id, period.year)
    equivalent = ZERO
    ending = (
        first <= employed_to <= last
        and profile is not None
        and (profile.last_working_day is not None and profile.last_working_day <= last)
    )
    if "equivalent_days" in components:
        equivalent = Decimal(components["equivalent_days"].amount)
    elif ending:
        equivalent, overused = await _equivalent_days(
            db, user_id, period.year, employed_from, employed_to
        )
        if overused:
            notes.append("equivalent_overused")
    base_override = components.get("sick_base")
    data = MonthInput(
        year=period.year,
        month=period.month,
        monthly_salary=Decimal(salary_row.monthly_amount),
        fte=Decimal(salary_row.fte),
        employed_from=employed_from,
        employed_to=employed_to,
        hired_on=hired or employed_from,
        insured_since=hired or employed_from,
        absences=await _absences(db, user_id, first, last),
        variable=Decimal(components["variable"].amount)
        if "variable" in components
        else ZERO,
        other=Decimal(components["other"].amount) if "other" in components else ZERO,
        bonuses=bonuses,
        history=rows,
        previous_sick=previous,
        sick_days_used=((period.year, used),) if used else (),
        equivalent_days=equivalent,
        sick_base_override=Decimal(base_override.amount) if base_override else None,
    )
    return data, notes


def with_person(
    data: MonthInput,
    *,
    birth_date: Optional[date],
    insured_since: Optional[date],
    waiting_exempt: bool,
) -> MonthInput:
    return replace(
        data,
        birth_date=birth_date,
        insured_since=insured_since or data.insured_since,
        waiting_exempt=waiting_exempt,
    )


def fingerprint(data: MonthInput) -> dict[str, Any]:
    """Wejście pozycji do skrótu listy (zmiana nieobecności = przelicz listę)."""

    return {
        "salary": str(data.monthly_salary),
        "fte": str(data.fte),
        "employed": [data.employed_from.isoformat(), data.employed_to.isoformat()],
        "hired_on": data.hired_on.isoformat(),
        "absences": [
            [
                item.key,
                item.leave_type,
                item.start.isoformat(),
                item.end.isoformat(),
                [[day.isoformat(), str(fraction)] for day, fraction in item.days],
                item.sick_rate,
                item.waiting_exempt,
            ]
            for item in data.absences
        ],
        "variable": str(data.variable),
        "other": str(data.other),
        "bonuses": str(data.bonuses),
        "history": [rules.basis_to_json(row) for row in data.history],
        "previous_sick": [
            data.previous_sick.last_day.isoformat(),
            str(data.previous_sick.base),
        ]
        if data.previous_sick
        else None,
        "sick_days_used": [list(item) for item in data.sick_days_used],
        "equivalent_days": str(data.equivalent_days),
        "sick_base_override": None
        if data.sick_base_override is None
        else str(data.sick_base_override),
    }


__all__ = [
    "Loaded",
    "fingerprint",
    "history",
    "load_period",
    "month_input",
    "with_person",
]
