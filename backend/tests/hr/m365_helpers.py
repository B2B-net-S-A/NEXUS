"""Wspólne przygotowanie danych dla testów Microsoft 365 („Ludzie w NEXUSIE”).

Osoby, kartoteki, urlopy z dniami i operacje w kolejce zakładane wprost
w bazie. Dane fikcyjne (repo jest publiczne).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import HrM365Operation, LeaveRequest, LeaveRequestDay
from app.models.hr_profile import EmployeeProfile
from app.models.user import User, UserRole
from app.services.hr.calendar import load_calendar
from app.services.hr.leave_m365 import LeaveSnapshot, plan_operations
from app.services.hr.m365 import outbox

WARSAW = ZoneInfo("Europe/Warsaw")
LONG_AGO = datetime(2000, 1, 1, tzinfo=timezone.utc)


def at(day: date, hour: int = 9, minute: int = 0) -> datetime:
    """Chwila (UTC) o podanej godzinie warszawskiej."""

    return datetime.combine(day, time(hour, minute), tzinfo=WARSAW).astimezone(
        timezone.utc
    )


async def make_user(
    db: AsyncSession,
    *,
    name: Optional[str] = None,
    role: str = "recruiter",
    profile: bool = True,
    manager_user_id: Optional[int] = None,
) -> User:
    marker = uuid.uuid4().hex[:10]
    user = User(
        email=f"m365-{marker}@example.com",
        name=name or f"Osoba {marker}",
        role=UserRole(role),
        roles=[role],
        is_active=True,
    )
    db.add(user)
    await db.flush()
    if profile:
        db.add(EmployeeProfile(user_id=user.id, manager_user_id=manager_user_id))
        await db.flush()
    return user


async def make_leave(
    db: AsyncSession,
    user: User,
    start: date,
    end: date,
    *,
    status: str = "approved",
    leave_type: str = "vacation",
    half_day: Optional[str] = None,
    substitute: Optional[User] = None,
    consent: bool = False,
    source: str = "self",
) -> LeaveRequest:
    leave = LeaveRequest(
        user_id=user.id,
        leave_type=leave_type,
        status=status,
        start_date=start,
        end_date=end,
        half_day=half_day,
        substitute_user_id=substitute.id if substitute else None,
        forward_mail_consent=consent,
        source=source,
    )
    db.add(leave)
    await db.flush()
    day = start
    while day <= end:
        if day.weekday() < 5:
            db.add(
                LeaveRequestDay(
                    leave_request_id=leave.id,
                    user_id=user.id,
                    day=day,
                    fraction=Decimal("0.5") if half_day else Decimal("1.0"),
                    paid=True,
                    active=status in ("pending", "approved"),
                )
            )
        day += timedelta(days=1)
    await db.flush()
    return leave


async def snapshot(db: AsyncSession, leave: LeaveRequest) -> LeaveSnapshot:
    calendar = await load_calendar(db, leave.start_date, leave.end_date)
    total = sum(
        (
            row
            for row in (
                await db.scalars(
                    select(LeaveRequestDay.fraction).where(
                        LeaveRequestDay.leave_request_id == leave.id
                    )
                )
            ).all()
        ),
        Decimal("0"),
    )
    return LeaveSnapshot(
        id=str(leave.id),
        user_id=leave.user_id,
        start=leave.start_date,
        end=leave.end_date,
        half_day=leave.half_day,
        total_days=total,
        substitute_user_id=leave.substitute_user_id,
        forward_mail_consent=leave.forward_mail_consent,
        oof_internal_message=leave.oof_internal_message,
        oof_external_message=leave.oof_external_message,
        return_on=calendar.next_working_day_after(leave.end_date),
    )


async def plan(
    db: AsyncSession, leave: LeaveRequest, event: str, *, today: date
) -> list[str]:
    """Operacje jak przy akceptacji/anulowaniu (``plan_operations`` + ``outbox``)."""

    kinds = []
    for op in plan_operations(event, await snapshot(db, leave), today=today):  # type: ignore[arg-type]
        await outbox.enqueue(
            db,
            user_id=leave.user_id,
            kind=op.kind,
            dedupe_key=op.dedupe_key,
            payload=op.payload,
            leave_request_id=leave.id,
        )
        kinds.append(op.kind)
    return kinds


async def make_due(db: AsyncSession, user_ids: list[int]) -> None:
    """Oczekujące operacje tych osób — termin dawno minął (niezależnie od zegara)."""

    await db.execute(
        update(HrM365Operation)
        .where(
            HrM365Operation.user_id.in_(user_ids), HrM365Operation.status == "pending"
        )
        .values(next_attempt_at=LONG_AGO)
    )


async def operations(db: AsyncSession, user_id: int) -> list[HrM365Operation]:
    rows = await db.scalars(
        select(HrM365Operation)
        .where(HrM365Operation.user_id == user_id)
        .order_by(HrM365Operation.id)
        .execution_options(populate_existing=True)
    )
    return list(rows.all())


def of_kind(ops: list[HrM365Operation], kind: str) -> list[HrM365Operation]:
    return [op for op in ops if op.kind == kind]


async def reset_reconcile_runs(db: AsyncSession) -> None:
    await db.execute(
        text("DELETE FROM hr_job_runs WHERE kind LIKE 'hr_m365_reconcile%'")
    )
    await db.commit()
