"""„Porządek w requestach” — DL decyduje, nad którymi requestami pracujemy.

Lista wszystkich opublikowanych rekrutacji z podpowiedzią stanu liczoną
z historii pipeline'u (``services/request_work_state``) i hurtowa zmiana
stanu. Czytają i zapisują: admin, Delivery Lead, Head of Recruitment.
„Mamy championa” zmienia się istniejącą trasą
``POST /api/jobs/{id}/champion-found`` — tu jest tylko zakładką.
"""

from datetime import datetime, timezone
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only

from app.api.deps import require_roles
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.client import Client
from app.models.job import Job, JobStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.request_work_state import (
    LABELS,
    VISIBLE_STATES,
    WorkStateError,
    load_signals,
    set_work_state,
    suggest,
    visible_state,
)

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)

WorkStateEditor = require_roles(UserRole.delivery_lead, UserRole.head_of_recruitment)

MAX_CHANGES = 200


class ReviewRow(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str]
    delivery_lead_name: Optional[str]
    deadline: Optional[str]
    state: str
    state_label: str
    last_work_at: Optional[datetime]
    last_cv_at: Optional[datetime]
    sent_total: int
    applications_14d: int
    suggested_state: Optional[str]
    suggestion_reason: str


class ReviewResponse(BaseModel):
    tab: str
    counts: dict[str, int]
    rows: list[ReviewRow]


class StateChange(BaseModel):
    job_id: int = Field(gt=0)
    state: Literal["to_review", "searching", "client_silent", "finished"]


class ChangesPayload(BaseModel):
    changes: list[StateChange] = Field(min_length=1, max_length=MAX_CHANGES)


def _listable():
    """Opublikowane requesty + zakończone w NEXUSIE (zakładka „Zakończone”)."""
    return or_(Job.status == JobStatus.published, Job.work_state == "finished")


@router.get("", response_model=ReviewResponse)
async def list_request_work_states(
    tab: Literal[
        "to_review", "searching", "champion", "client_silent", "finished"
    ] = Query("to_review"),
    mine: bool = Query(False),
    q: Optional[str] = Query(None, max_length=120),
    current_user: User = Depends(WorkStateEditor),
    db: AsyncSession = Depends(get_db),
) -> ReviewResponse:
    query = (
        select(Job)
        .where(_listable())
        .options(
            load_only(
                Job.id,
                Job.title,
                Job.client_id,
                Job.delivery_lead_id,
                Job.deadline,
                Job.work_state,
                Job.champion_found_at,
                Job.opened_at,
                Job.created_at,
                Job.status,
            )
        )
        .order_by(Job.deadline.asc().nulls_last(), Job.id.desc())
    )
    if mine:
        own_clients = select(DeliveryLeadClientAssignment.client_id).where(
            DeliveryLeadClientAssignment.delivery_lead_user_id == current_user.id
        )
        query = query.where(
            or_(
                Job.delivery_lead_id == current_user.id,
                Job.client_id.in_(own_clients),
            )
        )
    if q and q.strip():
        query = query.where(Job.title.ilike(f"%{q.strip()}%"))
    jobs = list((await db.scalars(query)).all())

    counts = {state: 0 for state in VISIBLE_STATES}
    visible = {}
    for job in jobs:
        state = visible_state(job.work_state, job.champion_found_at)
        visible[job.id] = state
        counts[state] += 1
    selected = [job for job in jobs if visible[job.id] == tab]

    now = datetime.now(timezone.utc)
    signals = await load_signals(db, selected, now=now)
    clients = dict(
        (
            await db.execute(
                select(Client.id, Client.name).where(
                    Client.id.in_({j.client_id for j in selected if j.client_id} or {0})
                )
            )
        ).all()
    )
    leads = dict(
        (
            await db.execute(
                select(User.id, User.name).where(
                    User.id.in_(
                        {j.delivery_lead_id for j in selected if j.delivery_lead_id}
                        or {0}
                    )
                )
            )
        ).all()
    )
    rows = []
    for job in selected:
        sig = signals[job.id]
        hint = suggest(sig, now)
        rows.append(
            ReviewRow(
                job_id=job.id,
                title=job.title,
                client_name=clients.get(job.client_id),
                delivery_lead_name=leads.get(job.delivery_lead_id),
                deadline=job.deadline.isoformat() if job.deadline else None,
                state=tab,
                state_label=LABELS[tab],
                last_work_at=sig.last_work_at,
                last_cv_at=sig.last_cv_at,
                sent_total=sig.sent_total,
                applications_14d=sig.applications_14d,
                suggested_state=hint.state,
                suggestion_reason=hint.reason,
            )
        )
    return ReviewResponse(tab=tab, counts=counts, rows=rows)


@router.patch("")
async def change_request_work_states(
    payload: ChangesPayload,
    current_user: User = Depends(WorkStateEditor),
    db: AsyncSession = Depends(get_db),
) -> dict:
    wanted = {change.job_id: change.state for change in payload.changes}
    jobs = list(
        (
            await db.scalars(
                select(Job)
                .where(Job.id.in_(list(wanted)))
                .order_by(Job.id)
                .with_for_update()
            )
        ).all()
    )
    if len(jobs) != len(wanted):
        raise HTTPException(404, "Część requestów nie istnieje.")
    changed = []
    try:
        for job in jobs:
            if await set_work_state(db, job, wanted[job.id], actor_id=current_user.id):
                changed.append(job.id)
    except WorkStateError as exc:
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return {"changed": changed, "unchanged": len(jobs) - len(changed)}
