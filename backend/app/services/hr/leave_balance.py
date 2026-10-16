"""Saldo urlopu — odczyt puli i zużycia z bazy („Ludzie w NEXUSIE”, E1).

Pula roku = wymiar + przeniesiony − wykorzystany przed NEXUSEM − aktywne dni
płatne z puli w tym roku (``leave_request_days.paid``, rok kalendarzowy dnia).
Brak wiersza ``leave_entitlements`` albo pusty wymiar = osoba bez puli.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.hr_profile import LeaveEntitlement
from app.services.hr.leave_policy import (
    CHILDCARE_YEARLY_LIMIT,
    CONTRACTOR_TYPES,
    ON_DEMAND_YEARLY_LIMIT,
    PoolYear,
    allowed_types,
)

_ZERO = Decimal("0")


@dataclass(frozen=True)
class YearUsage:
    approved_paid: Decimal = _ZERO
    pending_paid: Decimal = _ZERO
    unpaid: Decimal = _ZERO
    on_demand: Decimal = _ZERO
    childcare: Decimal = _ZERO


async def year_usage(
    db: AsyncSession,
    user_id: int,
    years: Iterable[int],
    *,
    exclude_request_id: object | None = None,
) -> dict[int, YearUsage]:
    """Aktywne dni osoby per rok: płatne z puli (zatwierdzone/oczekujące),
    bezpłatne z rodzajów puli, urlop na żądanie i opieka art. 188."""

    wanted = sorted(set(years))
    if not wanted:
        return {}
    year_col = extract("year", LeaveRequestDay.day)
    statement = (
        select(
            year_col.label("year"),
            LeaveRequest.status,
            LeaveRequest.leave_type,
            LeaveRequestDay.paid,
            func.sum(LeaveRequestDay.fraction),
        )
        .join(LeaveRequest, LeaveRequest.id == LeaveRequestDay.leave_request_id)
        .where(
            LeaveRequestDay.user_id == user_id,
            LeaveRequestDay.active.is_(True),
            year_col.in_(wanted),
        )
        .group_by(
            year_col, LeaveRequest.status, LeaveRequest.leave_type, LeaveRequestDay.paid
        )
    )
    if exclude_request_id is not None:
        statement = statement.where(LeaveRequest.id != exclude_request_id)
    totals: dict[int, dict[str, Decimal]] = {
        year: {
            "approved_paid": _ZERO,
            "pending_paid": _ZERO,
            "unpaid": _ZERO,
            "on_demand": _ZERO,
            "childcare": _ZERO,
        }
        for year in wanted
    }
    for year, status, leave_type, paid, amount in (await db.execute(statement)).all():
        bucket = totals[int(year)]
        amount = Decimal(amount or 0)
        if paid:
            key = "approved_paid" if status == "approved" else "pending_paid"
            bucket[key] += amount
        elif leave_type in ("vacation", "on_demand"):
            bucket["unpaid"] += amount
        if leave_type == "on_demand":
            bucket["on_demand"] += amount
        if leave_type == "childcare":
            bucket["childcare"] += amount
    return {year: YearUsage(**values) for year, values in totals.items()}


async def entitlements(
    db: AsyncSession, user_id: int, years: Iterable[int]
) -> dict[int, LeaveEntitlement]:
    rows = await db.scalars(
        select(LeaveEntitlement).where(
            LeaveEntitlement.user_id == user_id,
            LeaveEntitlement.year.in_(sorted(set(years))),
        )
    )
    return {row.year: row for row in rows}


async def pools_for(
    db: AsyncSession,
    user_id: int,
    years: Iterable[int],
    *,
    exclude_request_id: object | None = None,
) -> dict[int, PoolYear]:
    wanted = sorted(set(years))
    rows = await entitlements(db, user_id, wanted)
    usage = await year_usage(db, user_id, wanted, exclude_request_id=exclude_request_id)
    pools: dict[int, PoolYear] = {}
    for year in wanted:
        row = rows.get(year)
        used = usage.get(year, YearUsage())
        pools[year] = PoolYear(
            year=year,
            entitlement_days=row.entitlement_days if row else None,
            carried_over_days=row.carried_over_days if row else _ZERO,
            used_initial_days=row.used_initial_days if row else _ZERO,
            booked_paid_days=used.approved_paid + used.pending_paid,
            on_demand_days=used.on_demand,
            childcare_days=used.childcare,
        )
    return pools


def _num(value: Optional[Decimal]) -> Optional[str]:
    return None if value is None else f"{value:.1f}"


async def balance_payload(
    db: AsyncSession, *, user_id: int, year: int, employment_type: str
) -> dict[str, Any]:
    rows = await entitlements(db, user_id, [year])
    usage = (await year_usage(db, user_id, [year]))[year]
    row = rows.get(year)
    entitlement = row.entitlement_days if row else None
    carried = row.carried_over_days if row else _ZERO
    used_initial = row.used_initial_days if row else _ZERO
    remaining = (
        None
        if entitlement is None
        else entitlement
        + carried
        - used_initial
        - usage.approved_paid
        - usage.pending_paid
    )
    uop = employment_type not in CONTRACTOR_TYPES
    return {
        "year": year,
        "employment_type": employment_type,
        "has_pool": entitlement is not None,
        "entitlement_days": _num(entitlement),
        "carried_over_days": _num(carried),
        "used_initial_days": _num(used_initial),
        "approved_days": _num(usage.approved_paid),
        "pending_days": _num(usage.pending_paid),
        "unpaid_days": _num(usage.unpaid),
        "remaining_days": _num(remaining),
        "on_demand_used": _num(usage.on_demand) if uop else None,
        "on_demand_limit": _num(ON_DEMAND_YEARLY_LIMIT) if uop else None,
        "childcare_used": _num(usage.childcare) if uop else None,
        "childcare_limit": _num(CHILDCARE_YEARLY_LIMIT) if uop else None,
        "allowed_types": list(allowed_types(employment_type)),
    }
