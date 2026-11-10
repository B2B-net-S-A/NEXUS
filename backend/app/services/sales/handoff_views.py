"""Listy przekazanych spotkań: dla prowadzącego i dla osoby, która umawia.

Zawsze dla jednej, zalogowanej osoby. Liczby tygodniowe (umówione → odbyte →
zakwalifikowane) widzi tylko osoba, której dotyczą: bez celu, paska postępu
i rankingu (decyzja Artura z 10.11.2026).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.scheduling import business_date, local_day_start_utc
from app.models.sales import (
    SalesActivity,
    SalesCompany,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
    SalesPipelineStage,
)
from app.models.user import User
from app.services.sales.handoff import HISTORY_FIELD, NOT_FOUND_DETAIL, VERDICT_FIELD
from app.services.sales.handoff_state import (
    DEFAULT_DURATION,
    HELD_VERDICTS,
    Phase,
    block,
    booked_by,
    day_of,
    has_handoff,
    moment,
    phase_of,
    user_id_of,
)
from app.services.sales.kpi import recent_weeks, week_start
from app.services.sales.meeting_decisions import is_outlook

WEEKS = 4
#: Jak długo osoba, która umówiła, widzi werdykt na swojej liście.
BOOKER_VERDICT_DAYS = 14
BOOKER_ROWS = 30


@dataclass(frozen=True)
class Person:
    id: int
    name: str
    title: Optional[str]
    phone: Optional[str]
    email: Optional[str]
    do_not_contact: bool


@dataclass(frozen=True)
class HandoffView:
    opportunity_id: int
    title: str
    status: str
    stage_key: str
    stage_name: str
    company_id: int
    company_name: str
    host_id: Optional[int]
    host_name: Optional[str]
    booked_by_id: Optional[int]
    booked_by_name: Optional[str]
    booked_at: Optional[datetime]
    meeting_at: Optional[datetime]
    duration_minutes: int
    #: Termin czytany ze spotkania w kalendarzu Outlook, nie z formularza.
    from_calendar: bool
    service: Optional[str]
    problem: Optional[str]
    decision_maker: Optional[str]
    timing: Optional[str]
    contact: Optional[Person]
    confirmed_at: Optional[datetime]
    verdict: Optional[str]
    verdict_at: Optional[datetime]
    verdict_reason: Optional[str]
    return_on: Optional[date]
    phase: Phase
    #: Inne przekazane spotkanie tej osoby nachodzi na ten termin.
    clash: bool = False


@dataclass(frozen=True)
class WeekCount:
    week_start: date
    booked: int = 0
    held: int = 0
    qualified: int = 0


def _phone(contact: SalesContact) -> Optional[str]:
    return (contact.mobile_phone or contact.phone or "").strip() or None


async def _views(
    db: AsyncSession, opportunities: list[SalesOpportunity], now: datetime
) -> list[HandoffView]:
    blocks = {opp.id: block(opp) or {} for opp in opportunities}
    stage_ids = {opp.stage_id for opp in opportunities}
    company_ids = {opp.company_id for opp in opportunities}
    contact_ids = {opp.primary_contact_id for opp in opportunities} - {None}
    activity_ids = {
        user_id_of(data.get("meeting_activity_id")) for data in blocks.values()
    } - {None}
    user_ids = (
        {opp.owner_user_id for opp in opportunities}
        | {user_id_of(data.get("booked_by")) for data in blocks.values()}
    ) - {None}

    async def rows(model: Any, ids: set[Any]) -> dict[int, Any]:
        if not ids:
            return {}
        found = await db.execute(select(model).where(model.id.in_(ids)))
        return {item.id: item for item in found.scalars()}

    stages = await rows(SalesPipelineStage, stage_ids)
    companies = await rows(SalesCompany, company_ids)
    contacts = await rows(SalesContact, contact_ids)
    activities = await rows(SalesActivity, activity_ids)
    users = await rows(User, user_ids)

    views: list[HandoffView] = []
    for opp in opportunities:
        data = blocks[opp.id]
        stage = stages[opp.stage_id]
        activity = activities.get(user_id_of(data.get("meeting_activity_id")) or -1)
        from_calendar = bool(
            activity is not None
            and activity.opportunity_id == opp.id
            and is_outlook(activity)
            and activity.occurred_at is not None
        )
        meeting_at = (
            activity.occurred_at if from_calendar else moment(data.get("meeting_at"))
        )
        duration = int(
            (activity.duration_minutes if from_calendar else None)
            or data.get("duration_minutes")
            or DEFAULT_DURATION
        )
        verdict = data.get("verdict") if isinstance(data.get("verdict"), dict) else None
        confirmed_at = moment(data.get("confirmed_at"))
        closed = opp.status != "open" or opp.archived_at is not None
        contact = contacts.get(opp.primary_contact_id or -1)
        booker_id = user_id_of(data.get("booked_by"))
        host = users.get(opp.owner_user_id or -1)
        booker = users.get(booker_id or -1)
        views.append(
            HandoffView(
                opportunity_id=opp.id,
                title=opp.title,
                status=opp.status,
                stage_key=stage.key,
                stage_name=stage.name,
                company_id=opp.company_id,
                company_name=companies[opp.company_id].name,
                host_id=opp.owner_user_id,
                host_name=host.name if host is not None else None,
                booked_by_id=booker_id,
                booked_by_name=booker.name if booker is not None else None,
                booked_at=moment(data.get("booked_at")),
                meeting_at=meeting_at,
                duration_minutes=duration,
                from_calendar=from_calendar,
                service=data.get("service"),
                problem=data.get("problem"),
                decision_maker=data.get("decision_maker"),
                timing=data.get("timing"),
                contact=(
                    Person(
                        id=contact.id,
                        name=contact.full_name,
                        title=contact.title,
                        phone=_phone(contact),
                        email=contact.email,
                        do_not_contact=contact.do_not_contact_at is not None,
                    )
                    if contact is not None
                    else None
                ),
                confirmed_at=confirmed_at,
                verdict=verdict.get("kind") if verdict else None,
                verdict_at=moment(verdict.get("at")) if verdict else None,
                verdict_reason=verdict.get("reason") if verdict else None,
                return_on=day_of(verdict.get("return_on")) if verdict else None,
                phase=(
                    "done"
                    if verdict or closed
                    else phase_of(meeting_at, confirmed_at, now)
                ),
            )
        )
    return views


def _with_clashes(views: list[HandoffView]) -> list[HandoffView]:
    timed = [view for view in views if view.meeting_at is not None]
    clashing: set[int] = set()
    for index, first in enumerate(timed):
        first_end = first.meeting_at + timedelta(minutes=first.duration_minutes)
        for second in timed[index + 1 :]:
            second_end = second.meeting_at + timedelta(minutes=second.duration_minutes)
            if first.meeting_at < second_end and second.meeting_at < first_end:
                clashing |= {first.opportunity_id, second.opportunity_id}
    return [
        replace(view, clash=True) if view.opportunity_id in clashing else view
        for view in views
    ]


_FAR = datetime(9999, 1, 1, tzinfo=timezone.utc)
_LONG_AGO = datetime(1970, 1, 1, tzinfo=timezone.utc)


async def for_host(db: AsyncSession, user_id: int, now: datetime) -> list[HandoffView]:
    """„Przekazane do Ciebie”: po terminach, na końcu spotkania bez terminu."""

    opportunities = list(
        (
            await db.execute(
                select(SalesOpportunity).where(
                    SalesOpportunity.owner_user_id == user_id,
                    SalesOpportunity.status == "open",
                    SalesOpportunity.archived_at.is_(None),
                    has_handoff(),
                )
            )
        ).scalars()
    )
    views = [
        view for view in await _views(db, opportunities, now) if view.phase != "done"
    ]
    views.sort(
        key=lambda view: (
            view.meeting_at is None,
            view.meeting_at or view.booked_at or _FAR,
            view.opportunity_id,
        )
    )
    return _with_clashes(views)


def _booker_order(view: HandoffView) -> tuple[int, bool, float, int]:
    """Najpierw to, co wróciło do umówienia, potem czekające po terminach, potem werdykty."""

    if view.verdict is None:
        when = view.meeting_at or view.booked_at or _FAR
        return (1, view.meeting_at is None, when.timestamp(), view.opportunity_id)
    recency = -(view.verdict_at or _LONG_AGO).timestamp()
    return (0 if view.verdict == "no_show" else 2, False, recency, view.opportunity_id)


async def for_booker(
    db: AsyncSession, user_id: int, now: datetime
) -> list[HandoffView]:
    """Spotkania umówione przez tę osobę: co czeka i jaki zapadł werdykt."""

    opportunities = list(
        (
            await db.execute(
                select(SalesOpportunity)
                .where(
                    SalesOpportunity.archived_at.is_(None),
                    has_handoff(),
                    booked_by() == str(user_id),
                )
                .order_by(SalesOpportunity.id.desc())
                .limit(400)
            )
        ).scalars()
    )
    recent = now - timedelta(days=BOOKER_VERDICT_DAYS)
    views = []
    for view in await _views(db, opportunities, now):
        if view.verdict is None:
            # Własne spotkanie prowadzącego jest już w „Przekazane do Ciebie”.
            if view.phase != "done" and view.host_id != user_id:
                views.append(view)
        elif view.verdict == "no_show" and view.status == "open":
            views.append(view)
        elif view.verdict_at is not None and view.verdict_at >= recent:
            views.append(view)
    views.sort(key=_booker_order)
    return views[:BOOKER_ROWS]


async def for_opportunity(
    db: AsyncSession, opportunity_id: int, now: datetime
) -> Optional[HandoffView]:
    opportunity = await db.get(SalesOpportunity, opportunity_id)
    if opportunity is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=NOT_FOUND_DETAIL)
    if block(opportunity) is None:
        return None
    return (await _views(db, [opportunity], now))[0]


async def weeks_for_booker(
    db: AsyncSession, user_id: int, today: date
) -> list[WeekCount]:
    """Umówione → odbyte → zakwalifikowane w ostatnich tygodniach, od bieżącego.

    Liczone z historii szans: umówienie w tygodniu zapisu, odbycie i kwalifikacja
    w tygodniu werdyktu. Tylko dla osoby, która umówiła, bez celu i bez rankingu.
    """

    mondays = recent_weeks(today, WEEKS)
    counts = {monday: [0, 0, 0] for monday in mondays}
    events = await db.execute(
        select(
            SalesOpportunityEvent.field,
            SalesOpportunityEvent.new_value,
            SalesOpportunityEvent.created_at,
        )
        .join(
            SalesOpportunity,
            SalesOpportunity.id == SalesOpportunityEvent.opportunity_id,
        )
        .where(
            SalesOpportunityEvent.field.in_((HISTORY_FIELD, VERDICT_FIELD)),
            SalesOpportunityEvent.created_at >= local_day_start_utc(mondays[0]),
            has_handoff(),
            booked_by() == str(user_id),
        )
    )
    for field, value, created_at in events.all():
        bucket = counts.get(week_start(business_date(created_at)))
        if bucket is None:
            continue
        if field == HISTORY_FIELD and value == "booked":
            bucket[0] += 1
        elif field == VERDICT_FIELD and value in HELD_VERDICTS:
            bucket[1] += 1
            bucket[2] += value == "qualified"
    return [
        WeekCount(monday, *counts[monday]) for monday in sorted(counts, reverse=True)
    ]
