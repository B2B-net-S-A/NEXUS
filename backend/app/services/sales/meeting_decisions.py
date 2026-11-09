"""Spotkania z Outlooka: przypięcie do szansy i szansa założona ze spotkania.

Synchronizacja przypina aktywność do firmy, nie do szansy; szansę wskazuje
handlowiec. Przypięcie odświeża „ostatnią aktywność” szansy datą spotkania
(nie datą kliknięcia), a poprzednią wartość zapisuje w historii, bo przy
części szans z Atlasa nie da się jej odtworzyć z samych aktywności.

Historia trzyma id aktywności, nie temat: temat oznaczony później w Outlooku
jako prywatny znika wtedy także z niej (``forget`` czyści tylko wiersz).
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Optional

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent
from app.models.sales import (
    SalesActivity,
    SalesCompanyContact,
    SalesContact,
    SalesOpportunity,
    SalesOpportunityEvent,
)
from app.services import sales_schema as schema
from app.services.sales import history
from app.services.sales.outlook_activities import (
    EVENT_SOURCE,
    LAST_ACTIVITY_FIELD,
    raise_last_activity,
)
from app.services.sales_schema import OpportunityEventKind

OUTLOOK_SOURCE_PREFIX = "msgraph-"
OUTLOOK_FIELD = "outlook_activity"
OPPORTUNITY_SOURCE = "outlook-meeting"
NO_SUBJECT = "bez tematu"
_PEOPLE_LIMIT = 100

_LEADING_TAGS = re.compile(r"^\s*(?:\[[^\]]*\]\s*)+")
_OWN_NAME = r"(?:grupa\s+)?b2b\s*net(?:work)?(?:\s+s\.?a\.?)?(?:\s*\[[^\]]*\])?"
_JOIN = r"(?:\s+(?:x|×|vs\.?|i)\s+|\s*(?:-+>|→|&|\+|–|—|/|\|)\s*|\s+-\s+)"
_OWN_SUFFIX = re.compile(rf"{_JOIN}{_OWN_NAME}\s*$", re.IGNORECASE)
_OWN_PREFIX = re.compile(rf"^\s*{_OWN_NAME}{_JOIN}", re.IGNORECASE)


def clean_meeting_title(subject: Optional[str]) -> str:
    """Temat z kalendarza bez znaczników w nawiasie i bez naszej nazwy."""

    title = _LEADING_TAGS.sub("", subject or "")
    title = _OWN_SUFFIX.sub("", title)
    title = _OWN_PREFIX.sub("", title)
    return title.strip()


def is_outlook(activity: SalesActivity) -> bool:
    return (activity.external_source or "").startswith(OUTLOOK_SOURCE_PREFIX)


async def lock_activity(db: AsyncSession, activity_id: int) -> Optional[SalesActivity]:
    """Blokada wiersza: dwa kliknięcia nie założą dwóch szans z jednego spotkania."""

    return await db.scalar(
        select(SalesActivity).where(SalesActivity.id == activity_id).with_for_update()
    )


def _held_at(activity: SalesActivity, now: datetime) -> Optional[datetime]:
    """Kiedy to się odbyło; przyszłe spotkanie nie jest jeszcze śladem pracy."""

    when = activity.done_at or activity.occurred_at
    return when if when is not None and when <= now else None


def attach(
    db: AsyncSession,
    activity: SalesActivity,
    opportunity: SalesOpportunity,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Przypnij aktywność do szansy; wywołujący robi commit."""

    activity.opportunity_id = opportunity.id
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=OUTLOOK_FIELD,
        new_value=str(activity.id),
    )
    when = _held_at(activity, now)
    if when is not None:
        raise_last_activity(db, opportunity, when, user_id=user_id)


async def _freshest_other_work(
    db: AsyncSession, opportunity_id: int, activity_id: int, now: datetime
) -> Optional[datetime]:
    moment = func.coalesce(SalesActivity.done_at, SalesActivity.occurred_at)
    return await db.scalar(
        select(func.max(moment)).where(
            SalesActivity.opportunity_id == opportunity_id,
            SalesActivity.id != activity_id,
            moment <= now,
            or_(
                SalesActivity.done_at.is_not(None),
                SalesActivity.kind.not_in(schema.TASK_KINDS),
            ),
        )
    )


async def _date_before_pin(
    db: AsyncSession, opportunity_id: int, when: datetime
) -> tuple[bool, Optional[datetime]]:
    """Czy to przypięcie ustawiło datę i jaka była przed nim."""

    event = await db.scalar(
        select(SalesOpportunityEvent)
        .where(
            SalesOpportunityEvent.opportunity_id == opportunity_id,
            SalesOpportunityEvent.field == LAST_ACTIVITY_FIELD,
            SalesOpportunityEvent.new_value == history.as_text(when),
        )
        .order_by(SalesOpportunityEvent.id.desc())
        .limit(1)
    )
    if event is None:
        return False, None
    previous = datetime.fromisoformat(event.old_value) if event.old_value else None
    return True, previous


async def detach(
    db: AsyncSession,
    activity: SalesActivity,
    opportunity: SalesOpportunity,
    *,
    user_id: int,
    now: datetime,
) -> None:
    """Odepnij aktywność i cofnij datę ostatniej aktywności, jeśli to ona ją ustawiła."""

    when = _held_at(activity, now)
    activity.opportunity_id = None
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=OUTLOOK_FIELD,
        old_value=str(activity.id),
    )
    if when is None or opportunity.last_activity_at != when:
        return
    moved_by_pin, previous = await _date_before_pin(db, opportunity.id, when)
    if not moved_by_pin:
        return
    freshest = await _freshest_other_work(db, opportunity.id, activity.id, now)
    restored = max((m for m in (previous, freshest) if m is not None), default=None)
    history.record(
        db,
        opportunity_id=opportunity.id,
        user_id=user_id,
        kind=OpportunityEventKind.updated,
        field=LAST_ACTIVITY_FIELD,
        old_value=history.as_text(when),
        new_value=history.as_text(restored),
    )
    opportunity.last_activity_at = restored


async def company_people(db: AsyncSession, company_id: int) -> list[SalesContact]:
    """Bieżące kontakty firmy (główna firma kontaktu albo powiązanie)."""

    linked = select(SalesCompanyContact.contact_id).where(
        SalesCompanyContact.company_id == company_id,
        SalesCompanyContact.is_current.is_(True),
    )
    return list(
        (
            await db.scalars(
                select(SalesContact)
                .where(
                    SalesContact.archived_at.is_(None),
                    or_(
                        SalesContact.company_id == company_id,
                        SalesContact.id.in_(linked),
                    ),
                )
                .order_by(SalesContact.is_executive.desc(), SalesContact.full_name)
                .limit(_PEOPLE_LIMIT)
            )
        ).all()
    )


async def attendee_contact_ids(
    db: AsyncSession, activity: SalesActivity, people: list[SalesContact]
) -> set[int]:
    """Kto z kontaktów firmy był na spotkaniu: dopasowanie synchronizacji i uczestnicy."""

    if not activity.external_id:
        return {activity.contact_id} if activity.contact_id else set()
    matched = set(
        (
            await db.scalars(
                select(SalesActivity.contact_id).where(
                    and_(
                        SalesActivity.external_source == activity.external_source,
                        SalesActivity.external_id == activity.external_id,
                        SalesActivity.company_id == activity.company_id,
                        SalesActivity.contact_id.is_not(None),
                    )
                )
            )
        ).all()
    )
    addresses: set[str] = set()
    if activity.external_source == EVENT_SOURCE:
        for attendees in (
            await db.scalars(
                select(CalendarEvent.attendees).where(
                    CalendarEvent.m365_ical_uid == activity.external_id
                )
            )
        ).all():
            addresses |= {
                str(entry.get("address") or "").strip().lower()
                for entry in attendees or []
                if isinstance(entry, dict)
            }
    known = {person.id for person in people}
    by_address = {
        person.id
        for person in people
        if (person.email or "").strip().lower() in addresses
    }
    return (matched & known) | by_address
