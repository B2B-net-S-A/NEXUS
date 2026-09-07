"""Availability, explainable allocation and scoped operational task access."""

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.dialects.postgresql import insert

from app.api.deps import HeadOfRecruitmentOnly, OperationalUser
from app.api.section_access import PIPELINE_SECTION_DEPENDENCIES
from app.api.recruitment_access import ensure_job_membership
from app.core.config import settings
from app.core.database import get_db
from app.models.activity import Activity
from app.models.contract_onboarding import ContractOnboardingItem, OnboardingItemStatus
from app.models.job import Job, JobStatus
from app.models.recruitment_allocation import (
    RecruitmentAllocationEvent,
    RecruitmentAllocationRequest,
    RecruitmentAllocationState,
    WorkforceAvailabilityState,
)
from app.models.user import User
from app.services.operational_tasks import ownership_payload
from app.services.priority_work_service import (
    OPERATIONAL_ROLES,
    role_values,
    audit_event,
)
from app.services.recruitment_allocation import (
    allocation_lock,
    load_workloads,
    Workload,
)
from app.services.workforce_availability import effective_owner_ids, workforce_context

router = APIRouter(dependencies=PIPELINE_SECTION_DEPENDENCIES)


class AllocationModeUpdate(BaseModel):
    mode: Literal["off", "shadow", "auto"]


@router.get("/team")
async def team_allocation(current_user: HeadOfRecruitmentOnly, db=Depends(get_db)):
    context = await workforce_context(db)
    state = await db.get(RecruitmentAllocationState, 1)
    source = await db.get(WorkforceAvailabilityState, 1)
    loads = await load_workloads(db, context, now=datetime.now(timezone.utc))
    users = list(
        (
            await db.scalars(
                select(User)
                .where(User.is_active.is_(True))
                .order_by(User.name, User.id)
            )
        ).all()
    )
    names = {user.id: user.name or user.email for user in users}
    people = [
        {
            "user_id": user.id,
            "name": names[user.id],
            "available": user.id in context.available_ids,
            **loads.get(user.id, Workload()).as_payload(),
        }
        for user in users
        if role_values(user) & {role.value for role in OPERATIONAL_ROLES}
        or user.id in loads
    ]
    base = select(RecruitmentAllocationRequest, Job.title).join(
        Job, Job.id == RecruitmentAllocationRequest.job_id
    )
    # Pending work is never hidden behind a page of newer completed decisions.
    rows = list(
        (
            await db.execute(
                base.where(RecruitmentAllocationRequest.status == "queued").order_by(
                    case(
                        (Job.priority == "urgent", 0),
                        (Job.priority == "high", 1),
                        (Job.priority == "medium", 2),
                        else_=3,
                    ),
                    func.coalesce(RecruitmentAllocationRequest.due_at, Job.deadline)
                    .asc()
                    .nulls_last(),
                    RecruitmentAllocationRequest.created_at,
                    RecruitmentAllocationRequest.id,
                )
            )
        ).all()
    )
    rows.extend(
        (
            await db.execute(
                base.where(RecruitmentAllocationRequest.status != "queued")
                .order_by(RecruitmentAllocationRequest.created_at.desc())
                .limit(50)
            )
        ).all()
    )
    from app.tasks.recruitment_allocation import allocation_issues

    return {
        "enabled": settings.RECRUITMENT_ALLOCATION_ENABLED,
        "mode": state.mode if state else "off",
        "availability_fresh": context.fresh,
        "snapshot_version": context.snapshot_version,
        "last_sync_at": source.last_success_at if source else None,
        "sync_error": source.last_error if source else None,
        "last_run_at": state.last_run_at if state else None,
        "worker_error": state.last_error if state else None,
        "people": people,
        "delegations": [
            {
                **d.as_payload(),
                "owner_name": names.get(d.owner_id),
                "performer_name": names.get(d.performer_id),
            }
            for d in context.delegations.values()
        ],
        "issues": await allocation_issues(db, context, loads),
        "requests": [
            {
                "id": request.id,
                "job_id": request.job_id,
                "title": title,
                "status": request.status,
                "reason": request.reason,
                "decision": request.decision,
                "created_at": request.created_at,
                "person_name": names.get(
                    request.assigned_user_id or request.suggested_user_id
                ),
                "evaluated_at": request.evaluated_at,
            }
            for request, title in rows
        ],
    }


@router.put("/mode")
async def set_allocation_mode(
    body: AllocationModeUpdate, current_user: HeadOfRecruitmentOnly, db=Depends(get_db)
):
    if not settings.RECRUITMENT_ALLOCATION_ENABLED and body.mode != "off":
        raise HTTPException(409, "Moduł przydziałów nie jest jeszcze uruchomiony")
    await allocation_lock(db)
    context = await workforce_context(db, refresh=True)
    if body.mode == "auto" and not context.fresh:
        raise HTTPException(409, "Najpierw przywróć aktualne dane z COMPASS")
    await db.execute(
        insert(RecruitmentAllocationState).values(id=1).on_conflict_do_nothing()
    )
    state = await db.get(RecruitmentAllocationState, 1, populate_existing=True)
    previous = state.mode
    state.mode = body.mode
    audit_event(
        db,
        "allocation_mode_changed",
        actor_user_id=current_user.id,
        payload={"previous": previous, "mode": body.mode},
    )
    db.add(RecruitmentAllocationEvent(topic="allocation_mode_changed"))
    await db.commit()
    return {"mode": state.mode}


@router.get("/jobs/{job_id}")
async def job_allocation(
    job_id: int, current_user: OperationalUser, db=Depends(get_db)
):
    await ensure_job_membership(db, job_id=job_id, user=current_user)
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(404, "Rekrutacja nie istnieje")
    payload = await ownership_payload(
        db, job.recruiter_id, open_task=job.is_open and job.status != JobStatus.closed
    )
    ids = {
        item
        for item in (payload["owner_user_id"], payload["effective_user_id"])
        if item is not None
    }
    users = {
        user.id: user.name or user.email
        for user in (await db.scalars(select(User).where(User.id.in_(ids)))).all()
    }
    request = await db.scalar(
        select(RecruitmentAllocationRequest).where(
            RecruitmentAllocationRequest.job_id == job_id
        )
    )
    return {
        **payload,
        "owner_name": users.get(payload["owner_user_id"]),
        "effective_name": users.get(payload["effective_user_id"]),
        "favorite_sourcing_paused": job.favorite_sourcing_paused,
        "reason": request.reason if request else None,
        "decision": request.decision if request else None,
    }


@router.get("/mine")
async def my_work(current_user: OperationalUser, db=Depends(get_db)):
    context = await workforce_context(db)
    loads = await load_workloads(db, context, now=datetime.now(timezone.utc))
    return {
        "enabled": settings.COMPASS_AVAILABILITY_ENABLED,
        "workload": loads.get(current_user.id, Workload()).as_payload(),
        "delegations": [
            row.as_payload()
            for row in context.delegations.values()
            if current_user.id in {row.owner_id, row.performer_id}
        ],
    }


@router.get("/onboarding")
async def my_onboarding(
    current_user: OperationalUser, after: int = Query(0, ge=0), db=Depends(get_db)
):
    owners = await effective_owner_ids(db, current_user.id)
    rows = list(
        (
            await db.scalars(
                select(ContractOnboardingItem)
                .where(
                    ContractOnboardingItem.assigned_to.in_(owners),
                    ContractOnboardingItem.status == OnboardingItemStatus.pending,
                    ContractOnboardingItem.id > after,
                )
                .order_by(ContractOnboardingItem.id)
                .limit(101)
            )
        ).all()
    )
    return {
        "items": [
            {
                "id": row.id,
                "label": row.label,
                "due_date": row.due_date,
                **await ownership_payload(db, row.assigned_to),
            }
            for row in rows[:100]
        ],
        "next_cursor": rows[99].id if len(rows) > 100 else None,
    }


class CompleteOnboarding(BaseModel):
    status: Literal["done", "na"]


@router.patch("/onboarding/{item_id}")
async def complete_onboarding(
    item_id: int,
    body: CompleteOnboarding,
    current_user: OperationalUser,
    db=Depends(get_db),
):
    owners = await effective_owner_ids(db, current_user.id)
    item = await db.scalar(
        select(ContractOnboardingItem)
        .where(
            ContractOnboardingItem.id == item_id,
            ContractOnboardingItem.assigned_to.in_(owners),
            ContractOnboardingItem.status == OnboardingItemStatus.pending,
        )
        .with_for_update()
    )
    if item is None:
        raise HTTPException(
            404, "Otwarte zadanie nie istnieje lub nie jest przypisane do Ciebie"
        )
    item.status = OnboardingItemStatus(body.status)
    db.add(
        Activity(
            entity_type="contract_onboarding_item",
            entity_id=item.id,
            action="onboarding_completed",
            user_id=current_user.id,
            details={"owner_id": item.assigned_to, "status": body.status},
        )
    )
    await db.commit()
    return {"id": item.id, "status": item.status.value}
