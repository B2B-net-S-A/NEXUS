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
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import get_db, AsyncSessionLocal
from app.models.calendar_event import CalendarEvent, EventType, EventStatus
from app.models.candidate import Candidate
from app.models.job import Job
from app.models.client import Client
from app.models.notification import Notification, NotificationType
from app.api.deps import CurrentUser

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
    created_by: Optional[int]
    reminder_minutes: int
    status: str
    created_at: Optional[datetime]

    class Config:
        from_attributes = True


# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("/calendar/events", response_model=List[CalendarEventResponse])
async def list_events(
    current_user: CurrentUser,
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
            cand_r = await db.execute(select(Candidate).where(Candidate.id == ev.candidate_id))
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

        output.append(CalendarEventResponse(
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
            created_by=ev.created_by,
            reminder_minutes=ev.reminder_minutes,
            status=ev.status.value,
            created_at=ev.created_at,
        ))

    return output


@router.post("/calendar/events", response_model=CalendarEventResponse, status_code=201)
async def create_event(
    body: CalendarEventCreate,
    current_user: CurrentUser,
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
        cand_r = await db.execute(select(Candidate).where(Candidate.id == event.candidate_id))
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
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.get("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def get_event(
    event_id: int,
    current_user: CurrentUser,
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
        cand_r = await db.execute(select(Candidate).where(Candidate.id == event.candidate_id))
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
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.patch("/calendar/events/{event_id}", response_model=CalendarEventResponse)
async def update_event(
    event_id: int,
    body: CalendarEventUpdate,
    current_user: CurrentUser,
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
        cand_r = await db.execute(select(Candidate).where(Candidate.id == event.candidate_id))
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
        created_by=event.created_by,
        reminder_minutes=event.reminder_minutes,
        status=event.status.value,
        created_at=event.created_at,
    )


@router.delete("/calendar/events/{event_id}", status_code=204)
async def delete_event(
    event_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(CalendarEvent).where(CalendarEvent.id == event_id))
    event = result.scalar_one_or_none()
    if not event:
        raise HTTPException(status_code=404, detail="Wydarzenie nie znalezione")
    await db.delete(event)
    await db.commit()


# ── Background reminder task ──────────────────────────────────────────────────

async def _send_reminder(event: CalendarEvent):
    """Send 15-min reminder notification via WebSocket to the event creator."""
    # Import here to avoid circular imports
    from app.api import ws as ws_manager

    if not event.created_by:
        return

    async with AsyncSessionLocal() as db:
        notif = Notification(
            user_id=event.created_by,
            title="Przypomnienie o wydarzeniu",
            message=f"Za 15 minut: {event.title}",
            link=f"/calendar",
            notification_type=NotificationType.interview_scheduled,
        )
        db.add(notif)
        await db.commit()
        await db.refresh(notif)

    await ws_manager.notify_user(event.created_by, {
        "type": "notification",
        "data": {
            "id": notif.id,
            "title": notif.title,
            "message": notif.message,
            "link": notif.link,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
    })
    logger.info(f"Reminder sent for event {event.id} to user {event.created_by}")


async def calendar_reminder_loop():
    """
    Background loop that checks every minute for events starting in ~15 minutes
    and sends reminder notifications to the event creator.
    """
    reminded_ids: set = set()
    while True:
        try:
            now = datetime.now(timezone.utc)
            window_start = now + timedelta(minutes=14)
            window_end = now + timedelta(minutes=16)

            async with AsyncSessionLocal() as db:
                result = await db.execute(
                    select(CalendarEvent).where(
                        CalendarEvent.start_time >= window_start,
                        CalendarEvent.start_time <= window_end,
                        CalendarEvent.status == EventStatus.scheduled,
                    )
                )
                events = result.scalars().all()
                for event in events:
                    if event.id not in reminded_ids:
                        reminded_ids.add(event.id)
                        asyncio.create_task(_send_reminder(event))

            # Clean up old IDs periodically (keep last 1000)
            if len(reminded_ids) > 1000:
                reminded_ids.clear()

        except Exception as e:
            logger.warning(f"Calendar reminder loop error: {e}")

        await asyncio.sleep(60)
