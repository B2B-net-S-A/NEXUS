"""Rozmowa u klienta przełożona albo odwołana — powiadomienie ludzi pary (0500).

Zgłoszenie rekruterki (21.10.2026): terminy rozmów u klienta często się
zmieniają, a Delivery Lead nie dowiadywał się o zmianie w NEXUSIE — przy
edycji wydarzenia powiadomienie szło tylko dla prepu
(``prep_notifications.notify_prep_change``).

Adresaci: Delivery Lead rekrutacji, rekruter kandydata
(``interview_slots.default_recruiter_ids`` — ta sama reguła co przy prepie)
i właściciel wydarzenia, bez autora zmiany. Typ ``interview_changed`` należy
do kategorii „Rozmowy”, więc stoi w ikonie „Kalendarz”, z dymkiem.

Encja (``client_interview_<rodzaj>``, bez ID) — jak ``prep_changed*``: dzienny
dedup ``emit`` zjadałby drugie przełożenie tego samego dnia. Para jest w linku.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventType
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.notification import NotificationType
from app.models.user import User
from app.services import interview_slots, prep_invitation
from app.services.job_working_title import job_display_title_expr

InterviewChangeKind = Literal["moved", "cancelled"]


def _when(value: Optional[datetime]) -> str:
    return prep_invitation.when_label(value) if value is not None else "—"


def _short(value: Optional[datetime]) -> str:
    """„24.10, 14:00” w strefie firmy — do tytułu, który w okienku się ucina."""
    if value is None:
        return "—"
    aware = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    return f"{aware.astimezone(ZoneInfo(settings.BUSINESS_TZ)):%d.%m, %H:%M}"


async def _labels(db: AsyncSession, candidate_id: int, job_id: int) -> tuple[str, str]:
    row = (
        await db.execute(
            select(Candidate.name, Candidate.lastname).where(
                Candidate.id == candidate_id
            )
        )
    ).first()
    who = (
        " ".join(p for p in (row[0], row[1]) if p) if row else ""
    ) or f"Kandydat #{candidate_id}"
    title = await db.scalar(select(job_display_title_expr()).where(Job.id == job_id))
    return who, title or f"Rekrutacja #{job_id}"


async def interview_people(db: AsyncSession, event: CalendarEvent) -> set[int]:
    """Delivery Lead rekrutacji, rekruter kandydata i właściciel wydarzenia."""
    pair = (event.candidate_id, event.job_id)
    delivery_lead_id = await db.scalar(
        select(Job.delivery_lead_id).where(Job.id == event.job_id)
    )
    recruiter_id = (await interview_slots.default_recruiter_ids(db, [pair])).get(pair)
    owner_id = event.operational_owner_id or event.created_by
    return {i for i in (delivery_lead_id, recruiter_id, owner_id) if i}


async def notify_client_interview_change(
    db: AsyncSession,
    *,
    actor: User,
    event: CalendarEvent,
    kind: InterviewChangeKind,
    previous_start: Optional[datetime] = None,
) -> int:
    """Ktoś przełożył albo odwołał rozmowę u klienta — reszta pary to widzi.

    Wydarzenie bez pary (kandydat + rekrutacja) albo innego typu niż rozmowa
    u klienta nie ma komu dać znać. Zwraca liczbę wstawionych powiadomień.
    """
    if (
        event.event_type != EventType.client_interview
        or event.candidate_id is None
        or event.job_id is None
    ):
        return 0
    people = await interview_people(db, event)
    people.discard(actor.id)
    if not people:
        return 0

    from app.services.notification_triggers import emit  # noqa: PLC0415 — cykl

    who, what = await _labels(db, event.candidate_id, event.job_id)
    author = actor.name or "ktoś z zespołu"
    if kind == "moved":
        title = f"Rozmowa u klienta przełożona na {_short(event.start_time)}"
        message = f"{who} — {what}: zmiana od: {author}, było {_when(previous_start)}."
    else:
        title = "Rozmowa u klienta odwołana"
        message = (
            f"{who} — {what}: odwołana przez: {author} "
            f"(była {_when(event.start_time)})."
        )
    link = f"/calendar?cycle={event.candidate_id}-{event.job_id}"
    sent = 0
    for uid in sorted(people):
        created = await emit(
            db,
            user_id=uid,
            title=title,
            message=message,
            ntype=NotificationType.interview_changed,
            related_entity_type=f"client_interview_{kind}",
            related_entity_id=None,
            link=link,
        )
        sent += int(created is not None)
    return sent
