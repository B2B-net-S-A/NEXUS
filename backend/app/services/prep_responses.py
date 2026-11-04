"""Odpowiedź kandydata na prep i zmiany z Outlooka prowadzącego (0453, D5–D8).

Co ``TEAMS_PREP_POLL_MINUTES`` (pętla ``teams_prep_transcripts``) NEXUS czyta
nadchodzące prepy z kalendarza prowadzącego — tą samą aplikacją, która je
zakłada (bez nowych uprawnień): odpowiedź kandydata (``attendees[].status``),
proponowany termin (``proposedNewTime``), przełożenie i odwołanie zrobione
w Outlooku. Do 17.10.2026 NEXUS nie czytał odpowiedzi wcale, a zmianę
z Outlooka widział dopiero po starej godzinie prepu (``prep_transcripts``).

Subskrypcji Grapha (webhook) świadomie nie ma: kilkadziesiąt prepów w oknie
14 dni to kilkadziesiąt GET-ów na 10 minut, a subskrypcja wymaga odnawiania
co ≤ 3 dni i publicznego adresu zwrotnego.

Pierwszy odczyt prepu sprzed 0453 (``candidate_response IS NULL``) zapisuje
stan bez powiadomienia o „przyjął” — inaczej wdrożenie wysłałoby naraz
zaległe wpisy o wszystkich prepach. Odmowa i inny termin dzwonią zawsze: to
sprawa do załatwienia przed prepem.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.candidate import Candidate
from app.models.prep_meeting import PrepMeeting
from app.services import prep_notifications
from app.services.m365 import teams_prep_graph
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

WINDOW = timedelta(days=14)
BATCH = 200
NO_RESPONSE_BEFORE = timedelta(hours=24)
# Świeżo założony prep nie dostaje przypomnienia, zanim kandydat w ogóle
# zdążył otworzyć zaproszenie.
NO_RESPONSE_GRACE = timedelta(hours=2)
MOVE_TOLERANCE = timedelta(minutes=1)

_GRAPH_RESPONSES = {
    "accepted": "accepted",
    "tentativelyAccepted": "tentative",
    "declined": "declined",
}


def normalize_response(raw: Optional[str]) -> str:
    """Graph → słownik NEXUSA; ``none``/``notResponded``/``organizer`` = ``none``."""
    return _GRAPH_RESPONSES.get(raw or "", "none")


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _moved(a: Optional[datetime], b: Optional[datetime]) -> bool:
    a, b = _utc(a), _utc(b)
    if a is None or b is None:
        return False
    return abs(a - b) > MOVE_TOLERANCE


@dataclass
class ResponseStats:
    checked: int = 0
    responses: int = 0
    moved: int = 0
    cancelled: int = 0
    reminders: int = 0
    errors: int = 0

    @property
    def changed(self) -> bool:
        return bool(self.responses or self.moved or self.cancelled or self.reminders)


def reset_response(prep: PrepMeeting) -> None:
    """Nowy termin z NEXUSA: Outlook zeruje odpowiedzi zaproszonych."""
    prep.candidate_response = "none"
    prep.candidate_response_at = None
    prep.proposed_start = None
    prep.proposed_end = None


async def apply_response(
    db: AsyncSession,
    prep: PrepMeeting,
    event: CalendarEvent,
    attendee: Optional[teams_prep_graph.AttendeeResponse],
    now: datetime,
) -> bool:
    """Zapisz odpowiedź kandydata; ``True`` = zmiana (i powiadomienie, jeśli trzeba)."""
    new = normalize_response(attendee.response if attendee else None)
    proposed = (
        (attendee.proposed_start, attendee.proposed_end)
        if attendee is not None and attendee.proposed_start is not None
        else (None, None)
    )
    old = prep.candidate_response
    old_proposed = (_utc(prep.proposed_start), _utc(prep.proposed_end))
    if new == old and proposed == old_proposed:
        return False
    prep.candidate_response = new
    prep.candidate_response_at = (
        (attendee.time if attendee and attendee.time else now)
        if new != "none"
        else None
    )
    prep.proposed_start, prep.proposed_end = proposed
    first_read = old is None
    actionable = new == "declined" or proposed[0] is not None
    if first_read and not actionable:
        return True
    if new == "none" and not actionable:
        return True
    await prep_notifications.notify_candidate_response(db, prep=prep, event=event)
    return True


async def check_prep(
    db: AsyncSession,
    prep: PrepMeeting,
    event: CalendarEvent,
    now: datetime,
    stats: ResponseStats,
) -> None:
    """Jeden prep: stan spotkania w Outlooku prowadzącego → baza i powiadomienia."""
    try:
        data = await teams_prep_graph.get_event(prep.organizer_upn, event.external_id)
    except GraphRequestError as exc:
        if exc.status != 404:
            raise
        data = {"isCancelled": True}
    if data is None:
        return
    stats.checked += 1
    prep.outlook_checked_at = now
    if data.get("isCancelled"):
        event.status = EventStatus.cancelled
        if prep.transcript_status == "waiting":
            prep.transcript_status = "cancelled"
        await prep_notifications.notify_outlook_change(
            db, prep=prep, event=event, kind="cancelled"
        )
        stats.cancelled += 1
        return
    start, end = data.get("start"), data.get("end")
    if (
        start
        and end
        and (_moved(start, event.start_time) or _moved(end, event.end_time))
    ):
        from app.services.prep_meetings import reschedule_fetch  # noqa: PLC0415

        previous = event.start_time
        event.start_time, event.end_time = start, end
        reschedule_fetch(prep, end)
        await prep_notifications.notify_outlook_change(
            db, prep=prep, event=event, kind="moved", previous_start=previous
        )
        stats.moved += 1
    if data.get("join_url") and not event.online_meeting_url:
        event.online_meeting_url = data["join_url"]

    candidate_email = (
        await db.scalar(
            select(Candidate.email).where(Candidate.id == prep.candidate_id)
        )
        or ""
    ).lower()
    attendee = next(
        (a for a in data.get("attendees") or [] if a.email == candidate_email),
        None,
    )
    if await apply_response(db, prep, event, attendee, now):
        stats.responses += 1

    start_at = _utc(event.start_time)
    created = _utc(prep.created_at)
    if (
        prep.candidate_response in (None, "none")
        and prep.proposed_start is None
        and start_at is not None
        and now < start_at <= now + NO_RESPONSE_BEFORE
        and (created is None or created <= now - NO_RESPONSE_GRACE)
    ):
        stats.reminders += await prep_notifications.notify_no_response(
            db, prep=prep, event=event
        )


async def sync_upcoming(
    db: AsyncSession, now: Optional[datetime] = None
) -> ResponseStats:
    """Nadchodzące prepy (14 dni) — każdy we własnej transakcji."""
    now = now or datetime.now(timezone.utc)
    stats = ResponseStats()
    ids = list(
        (
            await db.scalars(
                select(PrepMeeting.id)
                .join(CalendarEvent, CalendarEvent.id == PrepMeeting.calendar_event_id)
                .where(
                    CalendarEvent.status == EventStatus.scheduled,
                    CalendarEvent.external_id.isnot(None),
                    CalendarEvent.start_time > now,
                    CalendarEvent.start_time <= now + WINDOW,
                )
                .order_by(CalendarEvent.start_time.asc())
                .limit(BATCH)
            )
        ).all()
    )
    await db.commit()
    for prep_id in ids:
        try:
            prep = await db.get(PrepMeeting, prep_id, populate_existing=True)
            event = (
                await db.get(
                    CalendarEvent, prep.calendar_event_id, populate_existing=True
                )
                if prep is not None
                else None
            )
            if prep is None or event is None or event.status != EventStatus.scheduled:
                await db.rollback()
                continue
            await check_prep(db, prep, event, now, stats)
            await db.commit()
        except Exception as exc:  # noqa: BLE001 — jeden prep nie zatrzymuje reszty
            logger.warning("prep responses %s: %s", prep_id, type(exc).__name__)
            await db.rollback()
            stats.errors += 1
    return stats
