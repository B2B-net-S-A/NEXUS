"""Prowadzący spotkania: komu można przekazać i kiedy ma zajęte.

Prowadzącym może być każde aktywne konto z „Sprzedaż: edycja”; roli „Handlowiec”
nie ma. Kalendarz to wydarzenia zsynchronizowane ze skrzynki prowadzącego
(``calendar_events``), bez nowego wywołania Graph: formularz dostaje same
przedziały, bez tytułów spotkań.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import local_day_start_utc
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.m365 import M365Connection
from app.models.sales import SalesActivity, SalesOpportunity
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.sales.handoff_state import DEFAULT_DURATION, booked_by, has_handoff
from app.services.sales.touch import not_cancelled

HOST_DETAIL = "Prowadzący musi być aktywnym kontem z uprawnieniem „Sprzedaż: edycja”."


async def sales_editors(db: AsyncSession) -> list[User]:
    """Aktywne konta z „Sprzedaż: edycja”: komu można przekazać spotkanie."""

    active = list(
        (
            await db.execute(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        ).scalars()
    )
    await resolve_effective_access(db, active)
    return [user for user in active if has_permission(user, ProductAction.sales_edit)]


async def default_host_id(
    db: AsyncSession, user_id: int, allowed: set[int]
) -> Optional[int]:
    """Prowadzący z ostatniego przekazania tej osoby, a bez niego najczęstszy."""

    rows = (
        await db.execute(
            select(SalesOpportunity.owner_user_id, booked_by())
            .where(has_handoff())
            .order_by(SalesOpportunity.id.desc())
            .limit(200)
        )
    ).all()
    others = [
        (owner, booker)
        for owner, booker in rows
        if owner in allowed and owner != user_id
    ]
    mine = next((owner for owner, booker in others if booker == str(user_id)), None)
    if mine is not None:
        return mine
    common = Counter(owner for owner, _ in others).most_common(1)
    return common[0][0] if common else None


async def ensure_host(db: AsyncSession, host_id: int) -> User:
    host = await db.get(User, host_id)
    if host is not None and host.is_active:
        await resolve_effective_access(db, [host])
        if has_permission(host, ProductAction.sales_edit):
            return host
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=HOST_DETAIL)


def _merged(spans: list[tuple[datetime, datetime]]) -> list[tuple[datetime, datetime]]:
    merged: list[tuple[datetime, datetime]] = []
    for start, end in sorted(span for span in spans if span[1] > span[0]):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


async def host_busy(
    db: AsyncSession, host_id: int, day: date
) -> tuple[bool, list[tuple[datetime, datetime]]]:
    """Zajęte przedziały prowadzącego w dniu firmy: same godziny, bez tytułów.

    Kalendarz to wydarzenia zsynchronizowane ze skrzynki prowadzącego; bez
    połączonej skrzynki zostają spotkania zapisane w Sprzedaży, a termin wpisuje
    się ręcznie. Wydarzenia całodniowe pomijamy: to zwykle przypomnienia.
    """

    start = local_day_start_utc(day)
    end = local_day_start_utc(day + timedelta(days=1))
    fallback = timedelta(minutes=DEFAULT_DURATION)
    connected = (
        await db.scalar(
            select(M365Connection.id)
            .where(
                M365Connection.user_id == host_id,
                M365Connection.is_active.is_(True),
                M365Connection.purpose == "personal",
            )
            .limit(1)
        )
    ) is not None
    spans: list[tuple[datetime, datetime]] = []
    if connected:
        events = await db.execute(
            select(CalendarEvent.start_time, CalendarEvent.end_time).where(
                CalendarEvent.created_by == host_id,
                CalendarEvent.status == EventStatus.scheduled,
                CalendarEvent.all_day.is_(False),
                CalendarEvent.start_time < end,
                CalendarEvent.start_time >= start - timedelta(days=1),
            )
        )
        for begins, ends in events.all():
            ends = ends or begins + fallback
            if ends > start:
                spans.append((max(begins, start), min(ends, end)))
    meetings = await db.execute(
        select(SalesActivity.occurred_at, SalesActivity.duration_minutes).where(
            SalesActivity.kind == "meeting",
            SalesActivity.created_by_user_id == host_id,
            SalesActivity.occurred_at >= start,
            SalesActivity.occurred_at < end,
            *not_cancelled(),
        )
    )
    for begins, minutes in meetings.all():
        ends = begins + timedelta(minutes=minutes or DEFAULT_DURATION)
        spans.append((begins, min(ends, end)))
    return connected, _merged(spans)
