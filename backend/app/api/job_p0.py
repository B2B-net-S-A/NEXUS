"""P0 — rekrutacja ultrapilna przez 24 h (decyzje Artura 27.10.2026).

* ``GET /api/p0-jobs`` — aktywne P0 dla górnego paska i pulpitu każdego
  (rekrutacje widzą wszyscy z sekcją Rekrutacje);
* ``POST /api/jobs/{id}/p0`` — Head of Recruitment albo admin ustawia P0
  z powodem i czasem (24 h, 48 h, do piątku); ponowne ustawienie nadpisuje;
* ``POST /api/jobs/{id}/p0/extend`` — „Przedłuż o 24 h”;
* ``DELETE /api/jobs/{id}/p0`` — „Zdejmij P0”;
* ``POST /api/jobs/{id}/p0/request`` — Delivery Lead rekrutacji prosi o P0
  (28.10.2026); ``POST …/p0/request/approve`` — HoR albo admin zatwierdza,
  ``DELETE …/p0/request`` — HoR albo admin odrzuca, DL wycofuje swoją.

Lista pokazuje P0 tylko zespołowi rekrutacji (rekruterzy i DL), HoR i admin
widzą wszystkie (``job_p0.visible_to``, decyzja Artura 28.10.2026).

Lista ma własną ścieżkę (nie ``/api/jobs/p0``), bo ``GET /api/jobs/{job_id}``
przechwyciłby ją z 422. Skutki liczy ``services/job_p0``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus, RecruiterPlus, get_db
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.models.job import Job
from app.services import job_p0

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class P0JobOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    p0_until: datetime
    p0_reason: Optional[str] = None
    p0_set_at: Optional[datetime] = None
    p0_set_by_name: Optional[str] = None
    delivery_lead_name: Optional[str] = None
    recruiters: list[str] = []


class P0RequestOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    reason: str
    duration: Literal["24h", "48h", "friday"]
    requested_at: datetime
    requested_by_name: Optional[str] = None


class P0ListOut(BaseModel):
    items: list[P0JobOut]
    can_set: bool
    # Oczekujące prośby DL o P0: HoR i admin — wszystkie, DL — swoje.
    requests: list[P0RequestOut] = []


class P0StateOut(BaseModel):
    job_id: int
    is_p0: bool
    p0_until: Optional[datetime] = None
    p0_reason: Optional[str] = None
    p0_set_at: Optional[datetime] = None
    p0_set_by_name: Optional[str] = None
    notified: int = 0


class P0RequestStateOut(BaseModel):
    job_id: int
    p0_requested: bool
    p0_request_reason: Optional[str] = None
    p0_request_duration: Optional[str] = None
    notified: int = 0


class P0SetBody(BaseModel):
    reason: str = Field(max_length=job_p0.REASON_MAX * 2)
    duration: Literal["24h", "48h", "friday"] = "24h"


@router.get("/p0-jobs", response_model=P0ListOut)
async def list_p0_jobs(user: RecruiterPlus, db: AsyncSession = Depends(get_db)):
    return {
        "items": await job_p0.list_active(db, user),
        "can_set": job_p0.can_set_p0(user),
        "requests": await job_p0.list_requests(db, user),
    }


async def _locked_job(db: AsyncSession, job_id: int) -> Job:
    job = await db.get(Job, job_id, with_for_update=True, populate_existing=True)
    if job is None:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    return job


async def _state(db: AsyncSession, job: Job, notified: int = 0) -> dict:
    name = await job_p0.set_by_name(db, job)
    return {
        "job_id": job.id,
        **job_p0.fields(job, set_by_name=name),
        "notified": notified,
    }


@router.post("/jobs/{job_id}/p0", response_model=P0StateOut)
async def set_job_p0(
    job_id: int,
    body: P0SetBody,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    try:
        await job_p0.set_p0(
            db, job, actor_id=user.id, reason=body.reason, duration=body.duration
        )
    except job_p0.P0Error as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    sent = await job_p0.notify_set(db, job, actor_id=user.id)
    await db.commit()
    await db.refresh(job)
    return await _state(db, job, notified=len(sent))


@router.post("/jobs/{job_id}/p0/extend", response_model=P0StateOut)
async def extend_job_p0(
    job_id: int,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    try:
        await job_p0.extend_p0(db, job, actor_id=user.id)
    except job_p0.P0Error as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    await db.commit()
    await db.refresh(job)
    return await _state(db, job)


@router.delete("/jobs/{job_id}/p0", response_model=P0StateOut)
async def clear_job_p0(
    job_id: int,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    await job_p0.clear_p0(db, job, actor_id=user.id)
    await db.commit()
    await db.refresh(job)
    return await _state(db, job)


@router.post("/jobs/{job_id}/p0/request", response_model=P0RequestStateOut)
async def request_job_p0(
    job_id: int,
    body: P0SetBody,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    if not job_p0.can_request_p0(user, job):
        raise HTTPException(403, job_p0.REQUEST_DENIED)
    try:
        await job_p0.request_p0(
            db, job, actor_id=user.id, reason=body.reason, duration=body.duration
        )
    except job_p0.P0Error as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    sent = await job_p0.notify_request(db, job, actor_id=user.id)
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, **job_p0.request_fields(job), "notified": len(sent)}


@router.post("/jobs/{job_id}/p0/request/approve", response_model=P0StateOut)
async def approve_job_p0_request(
    job_id: int,
    user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    try:
        await job_p0.approve_request(db, job, actor_id=user.id)
    except job_p0.P0Error as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    sent = await job_p0.notify_set(db, job, actor_id=user.id)
    await db.commit()
    await db.refresh(job)
    return await _state(db, job, notified=len(sent))


@router.delete("/jobs/{job_id}/p0/request", response_model=P0RequestStateOut)
async def reject_job_p0_request(
    job_id: int,
    user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
):
    job = await _locked_job(db, job_id)
    if not (job_p0.can_set_p0(user) or job_p0.can_request_p0(user, job)):
        raise HTTPException(
            403, "Prośbę o P0 odrzuca Head of Recruitment albo administrator."
        )
    try:
        await job_p0.reject_request(db, job, actor_id=user.id)
    except job_p0.P0Error as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.detail) from exc
    await db.commit()
    await db.refresh(job)
    return {"job_id": job.id, **job_p0.request_fields(job)}
