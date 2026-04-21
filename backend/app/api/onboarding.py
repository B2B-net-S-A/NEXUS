"""First-login onboarding endpoint.

Delivery Lead and Recruiter roles must complete a one-time role-specific
onboarding before the frontend unlocks the main shell. This module exposes
a single POST that branches on the caller's role, persists the selections,
and flips `users.profile_completed` to true.

Contract:
- Auth required (reuse `CurrentUser`).
- Idempotency: second call after completion returns 409.
- Wrong role (not DL / recruiter): 400.
- Invalid job ids: 400.
- Empty lists: accepted — flag still flips.
"""

from typing import List, Set

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.job import Job, JobPriority
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole
from app.schemas.onboarding import (
    OnboardingPayloadDL,
    OnboardingPayloadRecruiter,
    OnboardingResponse,
)
from app.schemas.user import UserResponse

router = APIRouter()


async def _validate_job_ids(db: AsyncSession, job_ids: List[int]) -> None:
    """Raise 400 if any id does not match an existing job."""
    if not job_ids:
        return
    unique_ids = list(set(job_ids))
    result = await db.execute(select(Job.id).where(Job.id.in_(unique_ids)))
    found: Set[int] = {row[0] for row in result.all()}
    missing = [jid for jid in unique_ids if jid not in found]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unknown job ids: {missing}",
        )


async def _apply_dl_onboarding(
    db: AsyncSession, payload_raw: dict
) -> OnboardingPayloadDL:
    payload = OnboardingPayloadDL.model_validate(payload_raw)
    await _validate_job_ids(
        db, payload.priority_job_ids + payload.needs_sourcing_job_ids
    )

    if payload.priority_job_ids:
        priority_ids = list(set(payload.priority_job_ids))
        result = await db.execute(select(Job).where(Job.id.in_(priority_ids)))
        for job in result.scalars().all():
            job.priority = JobPriority.high

    if payload.needs_sourcing_job_ids:
        sourcing_ids = list(set(payload.needs_sourcing_job_ids))
        result = await db.execute(select(Job).where(Job.id.in_(sourcing_ids)))
        for job in result.scalars().all():
            job.needs_sourcing = True

    return payload


async def _apply_recruiter_onboarding(
    db: AsyncSession, payload_raw: dict, user: User
) -> OnboardingPayloadRecruiter:
    payload = OnboardingPayloadRecruiter.model_validate(payload_raw)
    await _validate_job_ids(db, payload.active_job_ids)

    if payload.active_job_ids:
        rows = [
            {"job_id": jid, "user_id": user.id, "added_by": user.id}
            for jid in set(payload.active_job_ids)
        ]
        stmt = pg_insert(JobCollaborator).values(rows)
        # UNIQUE(job_id, user_id) — skip rows already present.
        stmt = stmt.on_conflict_do_nothing(index_elements=["job_id", "user_id"])
        await db.execute(stmt)

    return payload


@router.post(
    "/me/onboarding",
    response_model=OnboardingResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_onboarding(
    request: Request,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Submit role-specific onboarding payload and flip `profile_completed`.

    Body shape depends on `current_user.role`:
    - `delivery_lead` → `OnboardingPayloadDL`
    - `recruiter` → `OnboardingPayloadRecruiter`

    Any other role is rejected — those users are pre-completed by migration
    0031 and should never hit this endpoint.
    """
    if current_user.profile_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding already completed",
        )

    payload_raw = await request.json()

    if current_user.role == UserRole.delivery_lead:
        await _apply_dl_onboarding(db, payload_raw)
    elif current_user.role == UserRole.recruiter:
        await _apply_recruiter_onboarding(db, payload_raw, current_user)
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{current_user.role.value}' does not require onboarding",
        )

    current_user.profile_completed = True
    current_user.profile_completed_at = func.now()
    await db.flush()
    await db.refresh(current_user)
    return OnboardingResponse(user=UserResponse.model_validate(current_user))
