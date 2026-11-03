"""Router `/api/screening-calls` — umówiony telefon na screening.

Reguły są w ``services/screening_calls.py``. Dostęp jak przy „Biorę”: członek
rekrutacji z sekcji pipeline'u.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import RecruiterPlus
from app.api.recruitment_access import ensure_job_membership
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.calendar_event import CalendarEvent, EventStatus
from app.models.job import Job
from app.services import screening_calls as svc
from app.services.pipeline_realtime import broadcast_pipeline_changed

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class ScreeningCallCreate(BaseModel):
    candidate_id: int = Field(ge=1)
    job_id: int = Field(ge=1)
    start: datetime
    note: Optional[str] = Field(default=None, max_length=500)
    client_request_id: str = Field(min_length=16, max_length=80)


class ScreeningCallUpdate(BaseModel):
    start: datetime
    note: Optional[str] = Field(default=None, max_length=500)


class ScreeningCallOut(BaseModel):
    event_id: int
    candidate_id: int
    job_id: int
    start_time: datetime
    note: Optional[str] = None
    status: str
    # Czy blokada trafiła do Outlooka: added, updated, not_connected, failed.
    outlook: Optional[str] = None


def _out(event: CalendarEvent) -> ScreeningCallOut:
    return ScreeningCallOut(
        event_id=event.id,
        candidate_id=event.candidate_id,
        job_id=event.job_id,
        start_time=event.start_time,
        note=event.description,
        status=event.status.value,
    )


@router.post("", response_model=ScreeningCallOut, status_code=201)
async def book_screening_call(
    data: ScreeningCallCreate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ScreeningCallOut:
    job = await db.get(Job, data.job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    await ensure_job_membership(db, current_user, job.id)
    event = await svc.book(
        db,
        user=current_user,
        job=job,
        candidate_id=data.candidate_id,
        start=data.start,
        note=data.note,
    )
    actor_id = current_user.id
    job_id = job.id
    await db.commit()
    result = _out(event)
    result.outlook = await svc.add_to_outlook(
        db,
        event=event,
        candidate_id=data.candidate_id,
        client_request_id=data.client_request_id,
    )
    await broadcast_pipeline_changed(db, job_id, actor_id)
    return result


@router.put("/{event_id}", response_model=ScreeningCallOut)
async def reschedule_screening_call(
    event_id: int,
    data: ScreeningCallUpdate,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ScreeningCallOut:
    event = await svc.load_call(db, event_id)
    await svc.assert_can_manage(db, event, current_user)
    await svc.reschedule(
        db,
        event=event,
        start=data.start,
        note=data.note,
        note_given="note" in data.model_fields_set,
    )
    actor_id = current_user.id
    job_id = event.job_id
    await db.commit()
    result = _out(event)
    result.outlook = await svc.move_in_outlook(db, event)
    if job_id is not None:
        await broadcast_pipeline_changed(db, job_id, actor_id)
    return result


@router.post("/{event_id}/cancel", response_model=ScreeningCallOut)
async def cancel_screening_call(
    event_id: int,
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
) -> ScreeningCallOut:
    event = await svc.load_call(db, event_id)
    await svc.assert_can_manage(db, event, current_user)
    event.status = EventStatus.cancelled
    await svc.release_hold(db, event, datetime.now(timezone.utc))
    result = _out(event)
    actor_id = current_user.id
    job_id = event.job_id
    await db.commit()
    if job_id is not None:
        await broadcast_pipeline_changed(db, job_id, actor_id)
    return result
