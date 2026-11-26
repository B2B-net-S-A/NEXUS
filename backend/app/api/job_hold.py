"""Rekrutacja „Wstrzymana” — trasy (decyzje Artura 26.11.2026).

* ``GET /api/jobs/{id}/hold`` — stan, powód, termin, od kiedy i kto, czy
  patrzący może wstrzymać/wznowić, kto dostanie wiadomość i jego otwarte
  zgłoszenie (każdy, kto czyta rekrutację);
* ``PUT /api/jobs/{id}/hold`` — wstrzymaj albo zmień powód / termin;
* ``DELETE /api/jobs/{id}/hold`` — „Wznów rekrutację” (→ „Szukamy”);
* ``POST /api/jobs/{id}/hold/report`` — rekruter: „Słyszysz, że klient
  wstrzymał?” / „Zapytaj DL”;
* ``GET /api/hold-checks`` — panel DL „Czy te rekrutacje nadal trwają?”;
* ``POST /api/jobs/{id}/hold-check`` — DL: „Szukamy”.

Zapis stanu: te same osoby co dziś zmieniają stan pracy (``WorkStateEditor``:
Delivery Lead, Head of Recruitment, admin) w zakresie DL jak przy zamknięciu.
Reguły i treści: ``services/job_hold.py``.

Uwaga: moduł bez ``from __future__ import annotations`` — FastAPI czyta
adnotacje ciała w czasie rejestracji trasy.
"""

from datetime import date
from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, StringConstraints
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, get_db
from app.api.recruitment_access import (
    ensure_delivery_lead_job_visible,
    ensure_job_membership,
)
from app.api.request_work_states import WorkStateEditor
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.scheduling import business_today
from app.models.job import Job, JobStatus
from app.models.user import User, UserRole
from app.services import job_hold
from app.services.section_permissions import (
    ProductSection,
    SectionAccess,
    section_access_for_user,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

HoldEditorUser = Annotated[User, Depends(WorkStateEditor)]
HoldReason = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=1, max_length=job_hold.REASON_MAX
    ),
]
ReportNote = Annotated[
    str, StringConstraints(strip_whitespace=True, max_length=job_hold.NOTE_MAX)
]


class HoldRecipientOut(BaseModel):
    user_id: int
    name: str
    people: int


class HoldReportOut(BaseModel):
    at: str
    note: str


class JobHoldOut(BaseModel):
    job_id: int
    state: str
    reason: Optional[str] = None
    review_on: Optional[str] = None
    since: Optional[str] = None
    by_id: Optional[int] = None
    by_name: Optional[str] = None
    can_manage: bool = False
    recipients: list[HoldRecipientOut] = []
    my_open_report: Optional[HoldReportOut] = None


class HoldIn(BaseModel):
    reason: HoldReason
    review_on: Optional[date] = None
    notify: bool = True


class HoldReportIn(BaseModel):
    note: ReportNote = ""


class HoldCheckAnswerIn(BaseModel):
    answer: Literal["searching"]


class HoldSignalOut(BaseModel):
    kind: Literal["report", "note", "parked_still_working", "dl_silent"]
    at: str
    by_name: Optional[str] = None
    text: str


class HoldCheckItemOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    reference: Optional[str] = None
    priority: str
    work_state: str
    recruiter_moves_7d: int = 0
    recruiters_7d: int = 0
    signals: list[HoldSignalOut]


class HoldChecksOut(BaseModel):
    items: list[HoldCheckItemOut]
    total: int


class OkOut(BaseModel):
    ok: bool = True


def _is_state_editor(user: User) -> bool:
    """Lustro ``WorkStateEditor`` (admin przechodzi każdą bramkę ról)."""
    return user.has_role(UserRole.admin) or user.has_any_role(
        UserRole.delivery_lead, UserRole.head_of_recruitment
    )


async def _job(db: AsyncSession, job_id: int, *, lock: bool) -> Job:
    query = select(Job).where(Job.id == job_id)
    if lock:
        query = query.with_for_update()
    job = await db.scalar(query)
    if job is None:
        raise HTTPException(status_code=404, detail="Rekrutacja nie istnieje.")
    return job


async def _can_manage(db: AsyncSession, user: User, job: Job) -> bool:
    if job.status != JobStatus.published or not _is_state_editor(user):
        return False
    if section_access_for_user(user, ProductSection.pipeline) < SectionAccess.write:
        return False
    try:
        await ensure_delivery_lead_job_visible(job, user, db)
    except HTTPException:
        return False
    return True


def _refuse(error: job_hold.HoldError) -> HTTPException:
    return HTTPException(status_code=error.status, detail=error.detail())


async def _payload(db: AsyncSession, job: Job, user: User) -> dict:
    return await job_hold.hold_payload(
        db, job, viewer_id=user.id, can_manage=await _can_manage(db, user, job)
    )


@router.get("/jobs/{job_id}/hold", response_model=JobHoldOut)
async def get_job_hold(
    job_id: int, user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    job = await _job(db, job_id, lock=False)
    await ensure_delivery_lead_job_visible(job, user, db)
    return await _payload(db, job, user)


@router.put("/jobs/{job_id}/hold", response_model=JobHoldOut)
async def put_job_hold(
    job_id: int,
    body: HoldIn,
    user: HoldEditorUser,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, job_id, lock=True)
    await ensure_delivery_lead_job_visible(job, user, db)
    try:
        await job_hold.put_hold(
            db,
            job,
            actor_id=user.id,
            reason=body.reason,
            review_on=body.review_on,
            notify=body.notify,
            today=business_today(),
        )
    except job_hold.HoldError as error:
        raise _refuse(error) from error
    await db.commit()
    await db.refresh(job)
    return await _payload(db, job, user)


@router.delete("/jobs/{job_id}/hold", response_model=JobHoldOut)
async def delete_job_hold(
    job_id: int, user: HoldEditorUser, db: AsyncSession = Depends(get_db)
):
    job = await _job(db, job_id, lock=True)
    await ensure_delivery_lead_job_visible(job, user, db)
    try:
        await job_hold.end_hold(db, job, actor_id=user.id)
    except job_hold.HoldError as error:
        raise _refuse(error) from error
    await db.commit()
    await db.refresh(job)
    return await _payload(db, job, user)


@router.post(
    "/jobs/{job_id}/hold/report",
    response_model=OkOut,
    status_code=status.HTTP_201_CREATED,
)
async def report_job_hold(
    job_id: int,
    body: HoldReportIn,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, job_id, lock=True)
    # Zgłasza każdy, kto pracuje w pipeline tej rekrutacji (zapis sekcji
    # sprawdza bramka routera).
    await ensure_job_membership(db, user, job.id)
    try:
        await job_hold.report(db, job, actor_id=user.id, note=body.note)
    except job_hold.HoldError as error:
        raise _refuse(error) from error
    await db.commit()
    return OkOut()


@router.get("/hold-checks", response_model=HoldChecksOut)
async def list_hold_checks(
    user: HoldEditorUser,
    db: AsyncSession = Depends(get_db),
    all: bool = Query(
        False,
        description="Head of Recruitment i admin: wszystkie rekrutacje, nie tylko "
        "te, których jesteś Delivery Leadem.",
    ),
):
    everyone = all and (
        user.has_role(UserRole.admin) or user.has_role(UserRole.head_of_recruitment)
    )
    return await job_hold.hold_checks(db, viewer_id=user.id, all_jobs=everyone)


@router.post("/jobs/{job_id}/hold-check", response_model=OkOut)
async def answer_hold_check(
    job_id: int,
    body: HoldCheckAnswerIn,
    user: HoldEditorUser,
    db: AsyncSession = Depends(get_db),
):
    job = await _job(db, job_id, lock=True)
    await ensure_delivery_lead_job_visible(job, user, db)
    try:
        await job_hold.answer_check(db, job, actor_id=user.id)
    except job_hold.HoldError as error:
        raise _refuse(error) from error
    await db.commit()
    return OkOut()
