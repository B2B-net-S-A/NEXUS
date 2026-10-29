"""Rekrutacje bez ruchu — pasek na rekrutacji i „Jeszcze trwa” (28.10.2026).

* ``GET /api/jobs/{id}/idle`` — ile dni bez CV do klienta i odpowiedzi
  klienta, kiedy przypomnienie trafi do Head of Recruitment i kiedy NEXUS
  zamknie rekrutację; ``stage = null`` poniżej 14 dni (paska nie ma);
* ``POST /api/jobs/{id}/idle/snooze`` — „Jeszcze trwa”: licznik od teraz.

Obie dla tych, którzy mogą zamknąć rekrutację (``RecruitmentManageUser``
i zakres Delivery Leada, jak ``POST /api/jobs/{id}/close``). Reguła
i przebieg dzienny: ``services/job_idle.py``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje w czasie rejestracji trasy.
"""

from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db
from app.api.permission_access import RecruitmentManageUser
from app.api.recruitment_access import ensure_delivery_lead_job_visible
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.job import Job, JobStatus
from app.services import job_idle

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class JobIdleOut(BaseModel):
    stage: Optional[str] = None
    days: int = 0
    since: Optional[str] = None
    last_move_at: Optional[str] = None
    last_move_kind: Optional[str] = None
    remind_on: Optional[str] = None
    hor_on: Optional[str] = None
    close_on: Optional[str] = None
    snooze_count: int = 0


async def _visible_job(db: AsyncSession, job_id: int, user, *, lock: bool) -> Job:
    query = select(Job).where(Job.id == job_id)
    if lock:
        query = query.with_for_update()
    job = await db.scalar(query)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    await ensure_delivery_lead_job_visible(job, user, db)
    return job


@router.get("/jobs/{job_id}/idle", response_model=JobIdleOut)
async def get_job_idle(
    job_id: int,
    user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
):
    job = await _visible_job(db, job_id, user, lock=False)
    now = datetime.now(timezone.utc)
    state = await job_idle.state_for_job(db, job, now=now)
    return job_idle.state_payload(
        state, snoozes=await job_idle.snooze_count(db, job.id)
    )


@router.post("/jobs/{job_id}/idle/snooze", response_model=JobIdleOut)
async def snooze_job_idle(
    job_id: int,
    user: RecruitmentManageUser,
    db: AsyncSession = Depends(get_db),
):
    job = await _visible_job(db, job_id, user, lock=True)
    if job.status != JobStatus.published:
        raise HTTPException(
            status_code=409,
            detail={
                "code": "job_not_open",
                "message": "Rekrutacja nie jest otwarta — nie ma czego odkładać.",
            },
        )
    now = datetime.now(timezone.utc)
    await job_idle.snooze(db, job, actor_id=user.id, now=now)
    await db.commit()
    await db.refresh(job)
    state = await job_idle.state_for_job(db, job, now=now)
    return job_idle.state_payload(
        state, snoozes=await job_idle.snooze_count(db, job.id)
    )
