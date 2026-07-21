"""
Calendar API
Manages recruitment calendar events — interviews, screenings, prep calls, meetings, deadlines.
"""

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, List

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, and_, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db, AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventType, EventStatus
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.client import Client
from app.models.notification import Notification, NotificationType
from app.models.user import UserRole
from app.api.recruitment_access import (
    CalendarWriteAccess,
    RecruitmentReadAccess,
)

logger = logging.getLogger(__name__)

router = APIRouter()


# ── Schemas ────────────────────────────────────────────────────────────────────


class CalendarEventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    event_type: EventType = EventType.meeting
    start_time: datetime
    end_time: Optional[datetime] = None
    all_day: bool = False
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    attendees: Optional[list] = None
    location: Optional[str] = None
    teams_link: Optional[str] = None
    reminder_minutes: int = 15


class CalendarEventUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    event_type: Optional[EventType] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    all_day: Optional[bool] = None
    candidate_id: Optional[int] = None
    job_id: Optional[int] = None
    client_id: Optional[int] = None
    attendees: Optional[list] = None
    location: Optional[str] = None
    teams_link: Optional[str] = None
    reminder_minutes: Optional[int] = None
    status: Optional[EventStatus] = None


class CalendarEventResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    event_type: str
    start_time: datetime
    end_time: Optional[datetime]
    all_day: bool
    candidate_id: Optional[int]
    candidate_name: Optional[str]
    job_id: Optional[int]
    job_title: Optional[str]
    client_id: Optional[int]
    client_name: Optional[str]
    attendees: Optional[list]
    location: Optional[str]
    teams_link: Optional[str]
    # Phase 7.1 — Graph-generated Teams join URL + Stream recording URL.
    online_meeting_url: Optional[str] = None
    recording_url: Optional[str] = None
    created_by: Optional[int]
    reminder_minutes: int
    status: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("/calendar/events", response_model=List[CalendarEventResponse])
async def list_events(
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
    from_date: Optional[datetime] = Query(None),
    to_date: Optional[datetime] = Query(None),
    event_type: Optional[EventType] = Query(None),
    status: Optional[EventStatus] = Query(None),
):
    """List calendar events. Optionally filter by date range, type, status."""
    query = select(CalendarEvent)
    conditions = []
    if from_date:
        conditions.append(CalendarEvent.start_time >= from_date)
    if to_date:
        conditions.append(CalendarEvent.start_time <= to_date)
    if event_type:
        conditions.append(CalendarEvent.event_type == event_type)
    if status:
        conditions.append(CalendarEvent.status == status)
    if conditions:
        query = query.where(and_(*conditions))
    query = query.order_by(CalendarEvent.start_time)

    result = await db.execute(query)
    events = result.scalars().all()

    # Enrich with names
    output = []
    for ev in events:
        candidate_name = None
        job_title = None
        client_name = None

        if ev.candidate_id:
            cand_r = await db.execute(
                select(Candidate).where(Candidate.id == ev.candidate_id)
            )
            cand = cand_r.scalar_one_or_none()
            if cand:
                candidate_name = f"{cand.name} {cand.lastname}"

        if ev.job_id:
            job_r = await db.execute(select(Job).where(Job.id == ev.job_id))
            job = job_r.scalar_one_or_none()
            if job:
                job_title = job.title

        if ev.client_id:
            cli_r = await db.execute(select(Client).where(Client.id == ev.client_id))
            cli = cli_r.scalar_one_or_none()
            if cli:
                client_name = cli.name

        output.append(
            CalendarEventResponse(
                id=ev.id,
                title=ev.title,
                description=ev.description,
                event_type=ev.event_type.value,
                start_time=ev.start_time,
                end_time=ev.end_time,
                all_day=ev.all_day,
                candidate_id=ev.candidate_id,
                candidate_name=candidate_name,
                job_id=ev.job_id,
                job_title=job_title,
                client_id=ev.client_id,
                client_name=client_name,
                attendees=ev.attendees or [],
                location=ev.location,
                teams_link=ev.teams_link,
                online_meeting_url=ev.online_meeting_url,
                recording_url=ev.recording_url,
                created_by=ev.created_by,
                reminder_minutes=ev.reminder_minutes,
                status=ev.status.value,
                created_at=ev.created_at,
            )
        )

    return output


@router.post("/calendar/events", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    body: CalendarEventCreate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Create a new calendar event."""
    event = CalendarEvent(
        title=body.title,
        description=body.description,
        event_type=body.event_type,
        start_time=body.start_time,
        end_time=body.end_time,
        all_day=body.all_day,
        candidate_id=body.candidate_id,
        job_id=body.job_id,
        client_id=body.client_id,
        attendees=body.attendees or [],
        location=body.location,
        teams_link=body.teams_link,
        created_by=current_user.id,
        reminder_minutes=body.reminder_minutes,
        status=EventStatus.scheduled,
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)

    # Build enriched response
    candidate_name = None
    job_title = None
    client_name = None

    if event.candidate_id:
        cand_r = await db.execute(
            select(Candidate).where(Candidate.id == event.candidate_id)
        )
        cand = cand_r.scalar_one_or_none()
        if cand:
            candidate_name = f"{cand.name} {cand.lastname}"

    if event.job_id:
        job_r = await db.execute(select(Job).where(Job.id == event.job_id))
        job = job_r.scalar_one_or_none()
        if job:
            job_title = job.title

    if event.client_id:
        cli_r = await db.execute(select(Client).where(Client.id == event.client_id))
        cli = cli_r.scalar_one_or_none()
        if cli:
            client_name = cli.name

    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        candidate_id=event.candidate_id,
        candidate_name=candidate_name,
        job_id=event.job_id,
        job_title=job_title,
        client_id=event.client_id,
        client_name=client_name,
        attendees=event.attendees or [],
        location=event.location,
        teams_link=event.teams_link,
        online_meeting_url=event.online_meeting_url,
        recording_url=event.recording_url,
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.get("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: int,
    current_user: RecruitmentReadAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")

    candidate_name = None
    job_title = None
    client_name = None

    if event.candidate_id:
        cand_r = await db.execute(
            select(Candidate).where(Candidate.id == event.candidate_id)
        )
        cand = cand_r.scalar_one_or_none()
        if cand:
            candidate_name = f"{cand.name} {cand.lastname}"

    if event.job_id:
        job_r = await db.execute(select(Job).where(Job.id == event.job_id))
        job = job_r.scalar_one_or_none()
        if job:
            job_title = job.title

    if event.client_id:
        cli_r = await db.execute(select(Client).where(Client.id == event.client_id))
        cli = cli_r.scalar_one_or_none()
        if cli:
            client_name = cli.name

    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        candidate_id=event.candidate_id,
        candidate_name=candidate_name,
        job_id=event.job_id,
        job_title=job_title,
        client_id=event.client_id,
        client_name=client_name,
        attendees=event.attendees or [],
        location=event.location,
        teams_link=event.teams_link,
        online_meeting_url=event.online_meeting_url,
        recording_url=event.recording_url,
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.patch("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: int,
    body: CalendarEventUpdate,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")

    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(event, field, value)

    await db.commit()
    await db.refresh(event)

    candidate_name = None
    if event.candidate_id:
        cand_r = await db.execute(
            select(Candidate).where(Candidate.id == event.candidate_id)
        )
        cand = cand_r.scalar_one_or_none()
        if cand:
            candidate_name = f"{cand.name} {cand.lastname}"

    return CalendarEventResponse(
        id=event.id,
        title=event.title,
        description=event.description,
        event_type=event.event_type.value,
        start_time=event.start_time,
        end_time=event.end_time,
        all_day=event.all_day,
        candidate_id=event.candidate_id,
        candidate_name=candidate_name,
        job_id=event.job_id,
        job_title=None,
        client_id=event.client_id,
        client_name=None,
        attendees=event.attendees or [],
        location=event.location,
        teams_link=event.teams_link,
        online_meeting_url=event.online_meeting_url,
        recording_url=event.recording_url,
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.delete("/calendar/events/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")
    await db.delete(event)
    await db.commit()


# ── Conflict detection (Phase 5.4) ────────────────────────────────────────────
#
# Looks at the user's own `CalendarEvent` rows to surface overlaps inside a
# requested window (typically the slot a recruiter is about to book). This is
# complementary to the M365 free-busy endpoint (Phase 4d): free-busy queries
# Microsoft Graph for attendees' Outlook availability, while this endpoint
# stays inside Nexus and answers "do I already have a Nexus interview /
# screening / meeting in this window?".
#
# Default duration when `end_time IS NULL` is 1 hour — same heuristic the M365
# invite path uses for its minimum slot length.

_CONFLICT_DEFAULT_DURATION = timedelta(hours=1)
_CONFLICT_MAX_WINDOW = timedelta(days=7)


class CalendarConflictItem(BaseModel):
    id: int
    title: str
    event_type: str
    status: str
    start_time: datetime
    end_time: Optional[datetime]
    candidate_id: Optional[int]
    candidate_name: Optional[str]


class CalendarConflictsResponse(BaseModel):
    user_id: int
    start: datetime
    end: datetime
    conflicts: list[CalendarConflictItem]


def _validate_window(start: datetime, end: datetime) -> None:
    if start >= end:
        raise HTTPException(status_code=422, detail="`end` must be after `start`")
    if (end - start) > _CONFLICT_MAX_WINDOW:
        raise HTTPException(
            status_code=422,
            detail=f"window too large (max {_CONFLICT_MAX_WINDOW.days} days)",
        )


def _resolve_scope_user(requested_user_id: Optional[int], current_user) -> int:
    """Default: scan caller's own events. Cross-user lookups need admin/HoR."""
    if requested_user_id is None or requested_user_id == current_user.id:
        return current_user.id
    if not current_user.has_any_role(UserRole.admin, UserRole.head_of_recruitment):
        raise HTTPException(
            status_code=403,
            detail="Cross-user conflict lookups require admin/head_of_recruitment",
        )
    return requested_user_id


@router.get("/calendar/conflicts", response_model=CalendarConflictsResponse)
async def list_conflicts(
    current_user: RecruitmentReadAccess,
    start: datetime = Query(..., description="Window start (inclusive)"),
    end: datetime = Query(..., description="Window end (exclusive)"),
    exclude_event_id: Optional[int] = Query(
        None, description="Skip this event (use when editing existing)"
    ),
    user_id: Optional[int] = Query(
        None, description="Defaults to current user; admin-only override"
    ),
    db: AsyncSession = Depends(get_db),
):
    """Return calendar events that overlap [start, end) for the scoped user.

    Used by ScheduleInterviewModal to warn before booking on top of an existing
    interview/screening.
    """
    _validate_window(start, end)
    scope_user_id = _resolve_scope_user(user_id, current_user)

    effective_end = func.coalesce(
        CalendarEvent.end_time,
        CalendarEvent.start_time + _CONFLICT_DEFAULT_DURATION,
    )

    conditions = [
        CalendarEvent.created_by == scope_user_id,
        CalendarEvent.status != EventStatus.cancelled,
        CalendarEvent.start_time < end,
        effective_end > start,
    ]
    if exclude_event_id is not None:
        conditions.append(CalendarEvent.id != exclude_event_id)

    rows = (
        (
            await db.execute(
                select(CalendarEvent)
                .where(and_(*conditions))
                .order_by(CalendarEvent.start_time)
            )
        )
        .scalars()
        .all()
    )

    items: list[CalendarConflictItem] = []
    for ev in rows:
        candidate_name = None
        if ev.candidate_id:
            cand = await db.scalar(
                select(Candidate).where(Candidate.id == ev.candidate_id)
            )
            if cand:
                candidate_name = f"{cand.name} {cand.lastname}".strip()
        items.append(
            CalendarConflictItem(
                id=ev.id,
                title=ev.title,
                event_type=ev.event_type.value,
                status=ev.status.value,
                start_time=ev.start_time,
                end_time=ev.end_time,
                candidate_id=ev.candidate_id,
                candidate_name=candidate_name,
            )
        )

    return CalendarConflictsResponse(
        user_id=scope_user_id, start=start, end=end, conflicts=items
    )


class CalendarConflictsSummaryResponse(BaseModel):
    user_id: int
    start: datetime
    end: datetime
    # event_id -> ids of events that overlap with it inside the window
    pairs: dict[int, list[int]]


@router.get(
    "/calendar/conflicts-summary", response_model=CalendarConflictsSummaryResponse
)
async def conflicts_summary(
    current_user: RecruitmentReadAccess,
    start: datetime = Query(...),
    end: datetime = Query(...),
    user_id: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
):
    """Map each event in the window to ids of events it overlaps with.

    Frontend uses this to flag conflicting events on the calendar grid without
    having to fan out a per-event request.
    """
    _validate_window(start, end)
    scope_user_id = _resolve_scope_user(user_id, current_user)

    rows = (
        await db.execute(
            select(
                CalendarEvent.id,
                CalendarEvent.start_time,
                CalendarEvent.end_time,
            )
            .where(
                CalendarEvent.created_by == scope_user_id,
                CalendarEvent.status != EventStatus.cancelled,
                CalendarEvent.start_time < end,
                func.coalesce(
                    CalendarEvent.end_time,
                    CalendarEvent.start_time + _CONFLICT_DEFAULT_DURATION,
                )
                > start,
            )
            .order_by(CalendarEvent.start_time)
        )
    ).all()

    spans = [
        (
            row.id,
            row.start_time,
            row.end_time or (row.start_time + _CONFLICT_DEFAULT_DURATION),
        )
        for row in rows
    ]

    pairs: dict[int, list[int]] = {ev_id: [] for ev_id, _, _ in spans}
    # n is bounded by what fits in 7 days of a single user's calendar — a flat
    # O(n^2) sweep is fine here and keeps the result deterministic.
    for i in range(len(spans)):
        i_id, i_start, i_end = spans[i]
        for j in range(i + 1, len(spans)):
            j_id, j_start, j_end = spans[j]
            if j_start >= i_end:
                # spans are sorted by start_time → no further j can overlap i
                break
            if i_start < j_end and j_start < i_end:
                pairs[i_id].append(j_id)
                pairs[j_id].append(i_id)

    return CalendarConflictsSummaryResponse(
        user_id=scope_user_id, start=start, end=end, pairs=pairs
    )


# ── iCal URL import (Phase 7b.6) ──────────────────────────────────────────────


class ICalImportRequest(BaseModel):
    url: str
    since_days: int = 7
    source_tag: str = "ical"


@router.post("/calendar/import-ical")
async def import_ical(
    body: ICalImportRequest,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Pull events from a public iCal feed URL (Outlook/Google publish-as-iCal)."""
    from app.services.ical_import import import_ical_url

    # P0.8: https only (webcal is https under the hood). Plain http is rejected
    # so a feed cannot be pointed at an internal http service.
    raw_url = (body.url or "").strip()
    if not raw_url.startswith(("https://", "webcal://")):
        raise HTTPException(
            status_code=422, detail="URL musi zaczynać się od https:// lub webcal://"
        )
    url = raw_url.replace("webcal://", "https://", 1)
    res = await import_ical_url(
        db,
        url,
        since_days=body.since_days,
        source_tag=body.source_tag,
        creator_id=current_user.id,
    )
    return res.as_dict()


# ── Microsoft 365 calendar invites ────────────────────────────────────────────


class M365InviteRequest(BaseModel):
    candidate_id: int
    title: str
    description: Optional[str] = ""
    start: datetime
    end: datetime
    event_type: EventType = EventType.interview
    extra_attendees: list[str] = []
    invite_candidate: bool = True
    # Phase 7.1 — opt-in/out of Graph-generated Teams meeting. None lets the
    # service helper apply the event-type default (on for interview/screening).
    add_teams_meeting: Optional[bool] = None


@router.post(
    "/calendar/events/m365-invite",
    response_model=CalendarEventResponse,
    status_code=201,
)
async def create_m365_invite(
    body: M365InviteRequest,
    current_user: CalendarWriteAccess,
    db: AsyncSession = Depends(get_db),
):
    """Create a Graph event in the user's Outlook calendar + auto-invite candidate.

    Requires an active `M365Connection`. Falls through to 412 Precondition
    Failed when the user has not connected their mailbox yet.
    """
    from app.models.m365 import M365Connection
    from app.services.m365.calendar import create_event as m365_create_event

    if body.end <= body.start:
        raise HTTPException(status_code=422, detail="end must be after start")

    conn = await db.scalar(
        select(M365Connection).where(M365Connection.user_id == current_user.id)
    )
    if conn is None or not conn.is_active:
        raise HTTPException(
            status_code=412,
            detail="No active Microsoft 365 connection — connect under /settings.",
        )

    candidate = await db.get(Candidate, body.candidate_id)
    if candidate is None:
        raise HTTPException(status_code=404, detail="candidate not found")
    if body.invite_candidate and not candidate.email:
        raise HTTPException(
            status_code=422,
            detail="candidate has no email — cannot invite",
        )

    row = await m365_create_event(
        db,
        conn,
        candidate=candidate,
        title=body.title,
        description=body.description or "",
        start=body.start,
        end=body.end,
        event_type=body.event_type,
        extra_attendees=body.extra_attendees,
        invite_candidate=body.invite_candidate,
        with_teams_meeting=body.add_teams_meeting,
    )
    await db.commit()
    await db.refresh(row)

    return CalendarEventResponse(
        id=row.id,
        title=row.title,
        description=row.description,
        event_type=row.event_type.value if row.event_type else "meeting",
        start_time=row.start_time,
        end_time=row.end_time,
        all_day=row.all_day,
        candidate_id=row.candidate_id,
        candidate_name=f"{candidate.name} {candidate.lastname}".strip(),
        job_id=row.job_id,
        job_title=None,
        client_id=row.client_id,
        client_name=None,
        attendees=row.attendees,
        location=row.location,
        teams_link=row.teams_link,
        online_meeting_url=row.online_meeting_url,
        recording_url=row.recording_url,
        created_by=row.created_by,
        reminder_minutes=row.reminder_minutes,
        status=row.status.value if row.status else "scheduled",
        created_at=row.created_at,
    )


# ── Background reminder task ──────────────────────────────────────────────────


async def _dispatch_reminder(event_id: int) -> None:
    """Send one T-15min reminder, durably + atomically.

    Restart-safety (audyt P1): the reminder is deduped by a persisted
    `reminder_sent_at` stamp, not an in-memory set. We claim the row with
    `SELECT ... FOR UPDATE SKIP LOCKED` so at most one worker sends per event
    even with multiple uvicorn workers, then persist the Notification and the
    stamp in the SAME transaction. A restart re-scans the table and skips any
    event that already has a stamp — so no duplicate reminders.

    The WebSocket push happens AFTER commit (best-effort): the Notification row
    is already durable, so a dropped socket only means the user sees it in their
    notification list instead of a live toast.
    """
    # Import here to avoid circular imports
    from app.api import ws as ws_manager

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CalendarEvent)
            .where(CalendarEvent.id == event_id)
            .with_for_update(skip_locked=True)
        )
        if event is None:
            # Locked by another worker or deleted between scan and claim.
            return
        # Re-check under the lock — status may have changed, or another worker
        # may have won the race and already stamped it.
        if event.status != EventStatus.scheduled or event.reminder_sent_at is not None:
            return

        now = datetime.now(timezone.utc)
        if not event.created_by:
            # Nothing to notify, but stamp so we don't re-examine it every tick.
            event.reminder_sent_at = now
            await db.commit()
            return

        notif = Notification(
            user_id=event.created_by,
            title="Przypomnienie o wydarzeniu",
            message=f"Za 15 minut: {event.title}",
            link="/calendar",
            notification_type=NotificationType.interview_scheduled,
        )
        db.add(notif)
        event.reminder_sent_at = now
        await db.commit()

        # Capture scalars (session uses expire_on_commit=False, so these stay
        # populated) for the post-commit WS push.
        user_id = event.created_by
        payload = {
            "id": notif.id,
            "title": notif.title,
            "message": notif.message,
            "link": notif.link,
            "created_at": now.isoformat(),
        }

    await ws_manager.notify_user(user_id, {"type": "notification", "data": payload})
    logger.info("Reminder sent for event %s to user %s", event_id, user_id)


async def calendar_reminder_loop():
    """
    Background loop that checks every minute for events starting in ~15 minutes
    and sends reminder notifications to the event creator.

    Dedup is durable (`calendar_events.reminder_sent_at`) and the per-event send
    is atomic (`FOR UPDATE SKIP LOCKED`), so this is safe across restarts and
    multiple uvicorn workers — see `_dispatch_reminder`.
    """
    while True:
        try:
            now = datetime.now(timezone.utc)
            window_start = now + timedelta(minutes=14)
            window_end = now + timedelta(minutes=16)

            async with AsyncSessionLocal() as db:
                due_ids = (
                    await db.scalars(
                        select(CalendarEvent.id).where(
                            CalendarEvent.start_time >= window_start,
                            CalendarEvent.start_time <= window_end,
                            CalendarEvent.status == EventStatus.scheduled,
                            CalendarEvent.reminder_sent_at.is_(None),
                        )
                    )
                ).all()

            for event_id in due_ids:
                try:
                    await _dispatch_reminder(event_id)
                except asyncio.CancelledError:
                    raise
                except Exception:  # noqa: BLE001
                    logger.exception(
                        "calendar reminder dispatch failed for event %s", event_id
                    )

        except asyncio.CancelledError:
            raise
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Calendar reminder loop error: {e}")

        await asyncio.sleep(60)
