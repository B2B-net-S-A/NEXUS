"""Dzień wolny firmy dodany albo usunięty po złożeniu wniosku — przeliczenie dni.

Dzień wolny nie jest dniem roboczym: znika z aktywnych wniosków, które go
obejmują, i wraca do puli; odwołany dzień wolny wraca do wniosku. Płatność dni
liczy od nowa ``plan_days`` z pulą bez tego wniosku, a ``paid_days`` /
``unpaid_days`` wniosku to ``split_days`` z dni po zmianie (ta sama reguła co
przy złożeniu). Godziny zatwierdzonego urlopu idą przez ``time_hooks``,
Microsoft 365 bez zmian (okno urlopu od–do się nie zmienia).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest, LeaveRequestDay
from app.models.notification import NotificationType
from app.models.user import User
from app.services.hr import people
from app.services.hr.calendar import load_calendar, years_between
from app.services.hr.employment_terms import reports_absence, terms
from app.services.hr.leave_balance import pools_for
from app.services.hr.leave_policy import (
    ACTIVE_DAY_UNIQUE,
    POOL_TYPES,
    LeavePolicyError,
    plan_days,
    requested_days,
    split_days,
)
from app.services.hr.leave_recipients import (
    LINK_SELF,
    audit_request,
    days_label,
    format_range,
    notify,
    report_payroll_locked,
)

DayRow = tuple[date, Decimal, bool]


async def _replanned_days(
    db: AsyncSession,
    request: LeaveRequest,
    *,
    wanted: list[tuple[date, Decimal]],
    current: dict[date, LeaveRequestDay],
    employment_type: str,
) -> list[DayRow]:
    """Dni wniosku po zmianie kalendarza, z płatnością z puli bez tego wniosku.

    Pula wraca: dzień, który przestał być roboczy, zwalnia miejsce (kontraktor
    może dostać płatny dzień w zamian). Gdy plan się nie składa (brak dni
    roboczych, limit przekroczony przez sam dzień wolny), dni idą za
    kalendarzem, a płatność zostaje taka, jaka była.
    """

    try:
        pools = await pools_for(
            db,
            request.user_id,
            years_between(request.start_date, request.end_date),
            exclude_request_id=request.id,
        )
        plan = plan_days(
            leave_type=request.leave_type,
            employment_type=employment_type,
            days=wanted,
            pools=pools,
        )
        return [(item.day, item.fraction, item.paid) for item in plan.days]
    except LeavePolicyError:
        default_paid = request.leave_type in POOL_TYPES and not reports_absence(
            employment_type
        )
        return [
            (day, fraction, current[day].paid if day in current else default_paid)
            for day, fraction in wanted
        ]


async def _recount_request(
    db: AsyncSession, request: LeaveRequest
) -> Optional[dict[str, Any]]:
    """Przelicza dni jednego wniosku z kalendarzem firmy (``None`` = bez zmian)."""

    profile = await people.profile_of(db, request.user_id)
    employment_type = (profile.employment_type if profile else None) or "uop"
    calendar = await load_calendar(db, request.start_date, request.end_date)
    wanted = requested_days(
        calendar, request.start_date, request.end_date, request.half_day
    )
    current = {
        row.day: row
        for row in await db.scalars(
            select(LeaveRequestDay).where(
                LeaveRequestDay.leave_request_id == request.id
            )
        )
    }
    if {day for day, _ in wanted} == set(current):
        return None
    before = sum((row.fraction for row in current.values()), Decimal("0"))
    planned = await _replanned_days(
        db, request, wanted=wanted, current=current, employment_type=employment_type
    )
    target = {day: (fraction, paid) for day, fraction, paid in planned}
    removed = sorted(day for day in current if day not in target)
    for day in removed:
        await db.delete(current[day])
    await db.flush()
    added: list[date] = []
    conflicts = 0
    for day, (fraction, paid) in sorted(target.items()):
        row = current.get(day)
        if row is not None:
            row.fraction, row.paid = fraction, paid
            continue
        try:
            async with db.begin_nested():
                db.add(
                    LeaveRequestDay(
                        leave_request_id=request.id,
                        user_id=request.user_id,
                        day=day,
                        fraction=fraction,
                        paid=paid,
                        active=True,
                    )
                )
                await db.flush()
        except IntegrityError as exc:
            # Dzień zajęty w międzyczasie innym wnioskiem — zostaje przy tamtym.
            if ACTIVE_DAY_UNIQUE not in str(exc.orig):
                raise
            conflicts += 1
            continue
        added.append(day)
    split = split_days(
        (
            (fraction, paid)
            for day, (fraction, paid) in target.items()
            if day in current or day in added
        ),
        leave_type=request.leave_type,
    )
    await db.execute(
        update(LeaveRequest)
        .where(LeaveRequest.id == request.id)
        .values(paid_days=split.paid, unpaid_days=split.unpaid, updated_at=func.now())
    )
    await db.refresh(request)
    return {
        "before": before,
        "after": split.total,
        "removed": removed,
        "added": added,
        "conflicts": conflicts,
    }


async def recount_for_company_day_off(
    db: AsyncSession, *, day: date, actor: User, added: bool
) -> dict[str, Any]:
    """Dzień wolny firmy dodany (``added``) albo usunięty: przelicza dni
    aktywnych wniosków (oczekujących i zatwierdzonych) obejmujących ``day``.

    Ślad per wniosek, dzwonek osobie, godziny zatwierdzonego urlopu przez
    ``time_hooks``.
    """

    from app.services.hr import time_hooks

    requests = list(
        await db.scalars(
            select(LeaveRequest)
            .where(
                LeaveRequest.status.in_(("pending", "approved")),
                LeaveRequest.start_date <= day,
                LeaveRequest.end_date >= day,
            )
            .order_by(LeaveRequest.user_id, LeaveRequest.start_date)
            .with_for_update()
        )
    )
    counts: dict[str, Any] = {"requests": 0, "conflicts": 0, "payroll_locked": 0}
    reason = "company_day_off_added" if added else "company_day_off_removed"
    for request in requests:
        change = await _recount_request(db, request)
        if change is None:
            continue
        counts["requests"] += 1
        counts["conflicts"] += change["conflicts"]
        audit_request(
            db,
            actor_id=actor.id,
            request=request,
            action="leave_days_recounted",
            extra={
                "day": day.isoformat(),
                "reason": reason,
                "days_before": f"{change['before']:.1f}",
                "days_after": f"{change['after']:.1f}",
                "conflicts": change["conflicts"],
            },
        )
        subject = await db.get(User, request.user_id)
        if request.status == "approved" and subject is not None:
            locked: list[str] = []
            if change["removed"]:
                hooked = await time_hooks.on_leave_cancelled(
                    db, request.user_id, change["removed"]
                )
                locked.extend(hooked["locked_conflicts"])
            if change["added"]:
                hooked = await time_hooks.on_leave_approved(
                    db, request.user_id, change["added"]
                )
                locked.extend(hooked["locked_conflicts"])
            found = await report_payroll_locked(
                db,
                request=request,
                subject=subject,
                actor_id=actor.id,
                months=locked,
                event=reason,
            )
            counts["payroll_locked"] += len(found)
        delta = change["after"] - change["before"]
        if delta == 0:
            continue
        span = format_range(request.start_date, request.end_date)
        owner = await people.profile_of(db, request.user_id)
        form = owner.employment_type if owner else None
        # Słowa formy (D4): „Twoja przerwa” na B2B, „Twój urlop” na umowie o pracę.
        is_leave = request.leave_type in POOL_TYPES and not reports_absence(form)
        noun = terms(form)["absence_short"] if reports_absence(form) else "nieobecność"
        what = f"Twój urlop {span} jest" if is_leave else f"Twoja {noun} {span} jest"
        if delta < 0:
            change_text = ("krótszy" if is_leave else "krótsza") + (
                f" o {days_label(-delta)} — {day:%d.%m.%Y} to dzień wolny firmy."
            )
        else:
            change_text = ("dłuższy" if is_leave else "dłuższa") + (
                f" o {days_label(delta)} — {day:%d.%m.%Y} znów jest dniem roboczym."
            )
        await notify(
            db,
            [request.user_id],
            exclude={actor.id},
            title="Dni nieobecności przeliczone",
            message=f"{what} {change_text}",
            ntype=NotificationType.hr_leave_decided,
            link=LINK_SELF,
        )
    return counts


__all__ = ["recount_for_company_day_off"]
