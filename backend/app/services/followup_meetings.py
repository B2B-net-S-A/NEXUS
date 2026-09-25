"""Schedule candidate follow-ups in Teams and collect their transcripts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.calendar_event import CalendarEvent, EventStatus, EventType
from app.models.candidate import Candidate
from app.models.followup_meeting import FollowupMeeting
from app.models.user import User
from app.services import prep_meetings, teams_vtt
from app.services.m365 import teams_prep_graph
from app.services.m365.app_graph_client import AppOnlyTokenUnavailable
from app.services.m365.calendar import (
    M365_SOURCE,
    _build_event_payload,
    event_transaction_id,
)
from app.services.m365.graph_client import GraphRequestError

logger = logging.getLogger(__name__)

NOTICE = (
    "Spotkanie odbywa się w Microsoft Teams. Będzie automatycznie nagrywane i "
    "transkrybowane na potrzeby obsługi Twojej rekrutacji przez B2B.NET S.A. "
    "Transkrypt jest przechowywany w NEXUS i dostępny wewnętrznie zespołowi rekrutacji. "
    "Jeśli nie chcesz nagrania, zgłoś to prowadzącemu przed rozpoczęciem rozmowy."
)


async def create_followup_meeting(
    db: AsyncSession,
    *,
    candidate: Candidate,
    organizer: User,
    start: datetime,
    end: datetime,
    client_request_id: str,
) -> FollowupMeeting:
    if not prep_meetings.app_only_ready():
        raise HTTPException(
            status_code=503, detail="Integracja Teams nie jest skonfigurowana."
        )
    if not organizer.email or not candidate.email:
        raise HTTPException(
            status_code=422, detail="Prowadzący i kandydat muszą mieć adresy e-mail."
        )
    existing = await db.scalar(
        select(FollowupMeeting).where(
            FollowupMeeting.client_request_id == client_request_id
        )
    )
    if existing:
        if (
            existing.candidate_id != candidate.id
            or existing.organizer_user_id != organizer.id
        ):
            raise HTTPException(
                status_code=409, detail="Identyfikator żądania został już użyty."
            )
        return existing

    title = f"Follow-up: {candidate.name or ''} {candidate.lastname or ''}".strip()[
        :255
    ]
    payload = _build_event_payload(
        title=title,
        description=NOTICE,
        start=start,
        end=end,
        attendee_emails=[candidate.email],
        want_teams=True,
        transaction_id=event_transaction_id(
            owner_user_id=organizer.id,
            title=title,
            start=start,
            end=end,
            attendee_emails=[candidate.email],
            intent_id=f"followup|{candidate.id}|{client_request_id}",
        ),
    )
    try:
        created = await teams_prep_graph.create_event(organizer.email, payload)
    except AppOnlyTokenUnavailable as exc:
        raise HTTPException(
            status_code=503, detail="Integracja Teams nie jest skonfigurowana."
        ) from exc
    except GraphRequestError as exc:
        logger.warning("teams followup create: Graph %s", exc.status)
        raise HTTPException(
            status_code=409 if exc.status in (403, 404) else 502,
            detail="Outlook nie utworzył spotkania. Sprawdź dostęp prowadzącego do NEXUS-Meetings.",
        ) from exc

    event = CalendarEvent(
        title=title,
        description=NOTICE,
        event_type=EventType.meeting,
        start_time=start,
        end_time=end,
        all_day=False,
        attendees=[{"address": candidate.email}],
        candidate_id=candidate.id,
        status=EventStatus.scheduled,
        external_source=M365_SOURCE,
        external_id=created.graph_event_id,
        created_by=organizer.id,
        operational_owner_id=organizer.id,
        m365_change_key=created.change_key,
        online_meeting_url=created.join_url,
        reminder_minutes=15,
    )
    db.add(event)
    await db.flush()
    meeting = FollowupMeeting(
        candidate_id=candidate.id,
        calendar_event_id=event.id,
        organizer_user_id=organizer.id,
        organizer_upn=organizer.email,
        client_request_id=client_request_id,
        transcription_setup="pending",
        transcript_status="waiting",
        next_fetch_at=end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES),
    )
    db.add(meeting)
    await db.flush()
    try:
        meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
            organizer.email
        )
        if meeting.organizer_aad_id and created.join_url:
            meeting.online_meeting_id = await teams_prep_graph.find_online_meeting(
                meeting.organizer_aad_id, created.join_url
            )
        if not settings.TEAMS_PREP_AUTO_TRANSCRIBE:
            meeting.transcription_setup = "disabled"
        elif meeting.organizer_aad_id and meeting.online_meeting_id:
            await teams_prep_graph.enable_auto_transcription(
                meeting.organizer_aad_id, meeting.online_meeting_id
            )
            meeting.transcription_setup = "enabled"
        else:
            meeting.transcription_setup = "failed"
            meeting.last_error = "meeting_not_found"
    except GraphRequestError as exc:
        meeting.transcription_setup = "failed"
        meeting.last_error = f"setup_http_{exc.status}"
    except Exception as exc:  # noqa: BLE001 - invitation already exists
        meeting.transcription_setup = "failed"
        meeting.last_error = f"setup_{type(exc).__name__}"[:120]
    return meeting


async def fetch_due(db: AsyncSession, now: Optional[datetime] = None) -> int:
    """Fetch due transcripts with a row lease; failures remain retryable."""
    from app.services.prep_transcripts import backoff, parse_contents

    now = now or datetime.now(timezone.utc)
    rows = (
        await db.scalars(
            select(FollowupMeeting)
            .where(
                FollowupMeeting.transcript_status.in_(
                    ("waiting", "error", "forbidden")
                ),
                FollowupMeeting.next_fetch_at <= now,
            )
            .order_by(FollowupMeeting.next_fetch_at)
            .limit(20)
            .with_for_update(skip_locked=True)
        )
    ).all()
    for meeting in rows:
        meeting.next_fetch_at = now + timedelta(minutes=15)
    ids = [meeting.id for meeting in rows]
    await db.commit()
    fetched = 0
    for meeting_id in ids:
        try:
            meeting = await db.get(FollowupMeeting, meeting_id, populate_existing=True)
            if meeting is None:
                continue
            event = await db.get(CalendarEvent, meeting.calendar_event_id)
            if event is None or event.status == EventStatus.cancelled:
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                await db.commit()
                continue
            current = await teams_prep_graph.get_event(
                meeting.organizer_upn, event.external_id
            )
            if current and current.get("isCancelled"):
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                event.status = EventStatus.cancelled
                await db.commit()
                continue
            if current:
                event.start_time = current.get("start") or event.start_time
                event.end_time = current.get("end") or event.end_time
                event.online_meeting_url = (
                    current.get("join_url") or event.online_meeting_url
                )
            end = event.end_time or event.start_time
            if end.tzinfo is None:
                end = end.replace(tzinfo=timezone.utc)
            ready = end + timedelta(minutes=settings.TEAMS_PREP_FETCH_DELAY_MINUTES)
            if ready > now:
                meeting.next_fetch_at = ready
                meeting.transcript_status = "waiting"
                await db.commit()
                continue
            if not meeting.organizer_aad_id:
                meeting.organizer_aad_id = await teams_prep_graph.resolve_user_id(
                    meeting.organizer_upn
                )
            if (
                meeting.organizer_aad_id
                and not meeting.online_meeting_id
                and event.online_meeting_url
            ):
                meeting.online_meeting_id = await teams_prep_graph.find_online_meeting(
                    meeting.organizer_aad_id, event.online_meeting_url
                )
            refs = []
            if meeting.organizer_aad_id and meeting.online_meeting_id:
                refs = await teams_prep_graph.list_transcripts(
                    meeting.organizer_aad_id, meeting.online_meeting_id
                )
            if not refs:
                meeting.fetch_attempts += 1
                if now >= end + timedelta(
                    hours=settings.TEAMS_PREP_FETCH_GIVE_UP_HOURS
                ):
                    meeting.transcript_status = "missing"
                    meeting.next_fetch_at = None
                else:
                    meeting.transcript_status = "waiting"
                    meeting.next_fetch_at = now + backoff(meeting.fetch_attempts)
            else:
                contents = [
                    await teams_prep_graph.transcript_vtt(
                        meeting.organizer_aad_id, meeting.online_meeting_id, ref.id
                    )
                    for ref in refs
                ]
                cues, _ = parse_contents(contents)
                if cues:
                    meeting.transcript_vtt = "\n\n".join(contents)
                    meeting.transcript_text = teams_vtt.render_plain_text(cues)
                    meeting.transcript_fetched_at = now
                    meeting.transcript_status = "fetched"
                    meeting.next_fetch_at = None
                    meeting.last_error = None
                    fetched += 1
                else:
                    meeting.transcript_status = "missing"
                    meeting.next_fetch_at = None
                    meeting.last_error = "empty_transcript"
            await db.commit()
        except GraphRequestError as exc:
            if exc.status == 404:
                meeting.transcript_status = "cancelled"
                meeting.next_fetch_at = None
                await db.commit()
                continue
            meeting.transcript_status = "forbidden" if exc.status == 403 else "error"
            meeting.last_error = f"http_{exc.status}"
            meeting.fetch_attempts += 1
            meeting.next_fetch_at = now + (
                timedelta(hours=6)
                if exc.status == 403
                else backoff(meeting.fetch_attempts)
            )
            await db.commit()
        except Exception as exc:  # noqa: BLE001 - retry one meeting without stopping others
            await db.rollback()
            logger.warning(
                "teams followup %s: fetch failed (%s)", meeting_id, type(exc).__name__
            )
            retry = await db.get(FollowupMeeting, meeting_id)
            if retry is not None:
                retry.transcript_status = "error"
                retry.fetch_attempts += 1
                retry.next_fetch_at = now + backoff(retry.fetch_attempts)
                retry.last_error = type(exc).__name__[:120]
                await db.commit()
    return fetched
