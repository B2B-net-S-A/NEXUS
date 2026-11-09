"""Spotkania pary przy zamknięciu karty (zgłoszenie 09.11.2026).

Zamknięcie karty nie ruszało prepów ani rozmów, a zamknięta para znika
z ekranu „Rozmowy u klienta” razem z przyciskiem „Odwołaj”. Okno rezygnacji
i odrzucenia pokazuje więc spotkania przed nami i odwołuje wybrane.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.prep_meeting import PrepMeeting
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User, UserRole
from app.services.workforce_availability import operational_owner_ids

_NEXUS_TYPES = (EventType.prep_call, EventType.client_interview)
_CLOSED = (PipelineStage.rejected, PipelineStage.withdrawn)
_OVERSIGHT = (UserRole.admin, UserRole.head_of_recruitment)


@dataclass(frozen=True)
class PairMeeting:
    event_id: int
    kind: str  # prep | client_interview | outlook
    title: str
    start: datetime
    host: Optional[str]
    cancellable: bool

    def as_dict(self) -> dict:
        return asdict(self)


def _utc_key(value: datetime) -> float:
    return value.timestamp()


async def upcoming(
    db: AsyncSession, *, candidate_id: int, job_id: int, now: datetime
) -> list[PairMeeting]:
    """Spotkania przed nami. Zaproszenie z Outlooka o tej samej godzinie co prep
    albo rozmowa to kopia z synchronizacji, więc go nie pokazujemy."""
    events = (
        await db.scalars(
            select(CalendarEvent)
            .where(
                CalendarEvent.candidate_id == candidate_id,
                CalendarEvent.status == EventStatus.scheduled,
                CalendarEvent.start_time > now,
                or_(
                    and_(
                        CalendarEvent.job_id == job_id,
                        CalendarEvent.event_type.in_(_NEXUS_TYPES),
                    ),
                    and_(
                        CalendarEvent.event_type == EventType.meeting,
                        or_(
                            CalendarEvent.job_id.is_(None),
                            CalendarEvent.job_id == job_id,
                        ),
                    ),
                ),
            )
            .order_by(CalendarEvent.start_time, CalendarEvent.id)
        )
    ).all()
    if not events:
        return []
    preps = {
        row.calendar_event_id: row
        for row in (
            await db.scalars(
                select(PrepMeeting).where(
                    PrepMeeting.calendar_event_id.in_([e.id for e in events])
                )
            )
        ).all()
    }

    def host_id(event: CalendarEvent) -> Optional[int]:
        prep = preps.get(event.id)
        if prep is not None:
            return prep.organizer_user_id
        return event.operational_owner_id or event.created_by

    ids = {uid for uid in map(host_id, events) if uid}
    names = (
        dict(
            (await db.execute(select(User.id, User.name).where(User.id.in_(ids)))).all()
        )
        if ids
        else {}
    )
    nexus_starts = {
        _utc_key(e.start_time) for e in events if e.event_type in _NEXUS_TYPES
    }
    out: list[PairMeeting] = []
    for event in events:
        if event.event_type == EventType.meeting:
            if _utc_key(event.start_time) in nexus_starts:
                continue
            kind, title, cancellable = "outlook", event.title or "Spotkanie", False
        elif event.event_type == EventType.prep_call:
            prep = preps.get(event.id)
            kind = "prep"
            title = f"Prep {prep.prep_no}" if prep is not None else "Prep"
            cancellable = True
        else:
            kind, title, cancellable = "client_interview", "Rozmowa u klienta", True
        out.append(
            PairMeeting(
                event_id=event.id,
                kind=kind,
                title=title,
                start=event.start_time,
                host=names.get(host_id(event)),
                cancellable=cancellable,
            )
        )
    return out


async def ensure_can_close(
    db: AsyncSession, user: User, *, candidate_id: int, job_id: int
) -> None:
    """Karta jest zamknięta i zamknął ją wołający (albo admin/HoR)."""
    latest = (
        await db.scalars(
            select(CandidateStage)
            .where(
                CandidateStage.candidate_id == candidate_id,
                CandidateStage.job_id == job_id,
            )
            .order_by(CandidateStage.moved_at.desc(), CandidateStage.id.desc())
            .limit(1)
        )
    ).first()
    if latest is None or latest.stage not in _CLOSED:
        raise HTTPException(
            status_code=409,
            detail="Spotkania odwołasz po zamknięciu karty tej osoby.",
        )
    if user.has_any_role(*_OVERSIGHT):
        return
    if latest.moved_by not in operational_owner_ids(user):
        raise HTTPException(
            status_code=403,
            detail="Spotkania odwołuje osoba, która zamknęła kartę.",
        )


def _when(value: datetime) -> str:
    return value.astimezone(ZoneInfo(settings.BUSINESS_TZ)).strftime("%d.%m, %H:%M")


async def ask_to_cancel(
    db: AsyncSession,
    event: CalendarEvent,
    *,
    actor: User,
    job_id: int,
    row: PairMeeting,
) -> bool:
    """Zaproszenia z Outlooka NEXUS nie odwoła: prośba dzwonkiem do prowadzącego."""
    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl

    recipient = event.operational_owner_id or event.created_by
    if recipient is None:
        job = await db.get(Job, job_id)
        recipient = job.delivery_lead_id if job is not None else None
    if recipient is None or recipient == actor.id:
        return False
    created = await emit(
        db,
        user_id=recipient,
        title="Odwołaj spotkanie w Outlooku",
        message=(
            f"Proces tej osoby jest zamknięty (zamyka: {actor.name or 'ktoś z zespołu'}). "
            f"Zaproszenie „{row.title}” ({_when(row.start)}) jest w Outlooku "
            "i NEXUS go nie odwoła."
        ),
        ntype=NotificationType.prep_changed_yours,
        related_entity_type="pair_meeting_cancel",
        related_entity_id=event.id,
        link=f"/calendar?view=week&event={event.id}",
    )
    return created is not None
