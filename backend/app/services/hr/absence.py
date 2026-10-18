"""Kto jest nieobecny — odczyty bez rodzaju nieobecności (D6).

* ``absences_on`` — zbiorczo dla listy osób w dniu (plakietka przy osobie
  w całym NEXUSIE),
* ``absent_on`` — „Nieobecni dziś” (osoba, do kiedy, zastępca),
* ``month_absences`` — kalendarz zespołu.

Nieobecność = zatwierdzony wniosek obejmujący dzień. „Do kiedy” łączy
wnioski, które idą jeden po drugim (urlop do piątku + kolejny od poniedziałku
to jedna nieobecność). Rodzaj i notatkę dokłada tylko ``month_absences`` dla
widzów z kręgu D6 (osoba, przełożony, Kadry, admin).
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_leave import LeaveRequest
from app.models.user import User
from app.services.hr.calendar import WorkCalendar, load_calendar

#: Jak daleko szukamy wniosków „ciągnących” nieobecność dalej.
_CHAIN_HORIZON_DAYS = 120


@dataclass(frozen=True)
class Absence:
    user_id: int
    until: date
    half_day: Optional[str]
    substitute_user_id: Optional[int]
    substitute_name: Optional[str]


def chain_until(
    spans: list[tuple[date, date]], covering_end: date, calendar: WorkCalendar
) -> date:
    """Koniec nieobecności po doklejeniu wniosków zaczynających się zaraz po."""

    until = covering_end
    for start, end in sorted(spans):
        if end <= until:
            continue
        if start <= calendar.next_working_day_after(until):
            until = end
    return until


async def absences_on(
    db: AsyncSession, user_ids: Iterable[int], on: date
) -> dict[int, Absence]:
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    rows = (
        await db.execute(
            select(
                LeaveRequest.user_id,
                LeaveRequest.start_date,
                LeaveRequest.end_date,
                LeaveRequest.half_day,
                LeaveRequest.substitute_user_id,
            ).where(
                LeaveRequest.user_id.in_(ids),
                LeaveRequest.status == "approved",
                LeaveRequest.end_date >= on,
                LeaveRequest.start_date <= on + timedelta(days=_CHAIN_HORIZON_DAYS),
            )
        )
    ).all()
    if not rows:
        return {}
    calendar = await load_calendar(db, on, on + timedelta(days=_CHAIN_HORIZON_DAYS))
    spans: dict[int, list[tuple[date, date]]] = {}
    covering: dict[int, tuple[date, Optional[str], Optional[int]]] = {}
    for user_id, start, end, half_day, substitute_id in rows:
        spans.setdefault(user_id, []).append((start, end))
        if start <= on <= end:
            covering[user_id] = (end, half_day, substitute_id)
    substitute_ids = {sub for _, _, sub in covering.values() if sub}
    names: dict[int, str] = {}
    if substitute_ids:
        names = dict(
            (
                await db.execute(
                    select(User.id, User.name).where(User.id.in_(substitute_ids))
                )
            ).all()
        )
    result: dict[int, Absence] = {}
    for user_id, (end, half_day, substitute_id) in covering.items():
        result[user_id] = Absence(
            user_id=user_id,
            until=chain_until(spans[user_id], end, calendar),
            half_day=half_day,
            substitute_user_id=substitute_id,
            substitute_name=names.get(substitute_id) if substitute_id else None,
        )
    return result


async def absent_on(db: AsyncSession, on: date) -> list[Absence]:
    """Wszyscy nieobecni w dniu (osoby z aktywnym kontem)."""

    user_ids = await db.scalars(
        select(LeaveRequest.user_id)
        .join(User, User.id == LeaveRequest.user_id)
        .where(
            LeaveRequest.status == "approved",
            LeaveRequest.start_date <= on,
            LeaveRequest.end_date >= on,
            User.is_active.is_(True),
        )
        .distinct()
    )
    found = await absences_on(db, list(user_ids), on)
    return sorted(found.values(), key=lambda absence: (absence.until, absence.user_id))


@dataclass(frozen=True)
class MonthAbsence:
    id: str
    user_id: int
    start: date
    end: date
    half_day: Optional[str]
    status: str
    leave_type: str
    substitute_user_id: Optional[int]


async def month_absences(
    db: AsyncSession,
    user_ids: Iterable[int],
    first: date,
    last: date,
    *,
    pending_for: Iterable[int] = (),
) -> list[MonthAbsence]:
    """Zatwierdzone wnioski w miesiącu; oczekujące tylko dla ``pending_for``."""

    ids = sorted(set(user_ids))
    if not ids:
        return []
    pending_ids = set(pending_for)
    rows = await db.scalars(
        select(LeaveRequest)
        .where(
            LeaveRequest.user_id.in_(ids),
            LeaveRequest.status.in_(("approved", "pending")),
            LeaveRequest.start_date <= last,
            LeaveRequest.end_date >= first,
        )
        .order_by(LeaveRequest.start_date)
    )
    return [
        MonthAbsence(
            id=str(row.id),
            user_id=row.user_id,
            start=row.start_date,
            end=row.end_date,
            half_day=row.half_day,
            status=row.status,
            leave_type=row.leave_type,
            substitute_user_id=row.substitute_user_id,
        )
        for row in rows
        if row.status == "approved" or row.user_id in pending_ids
    ]
