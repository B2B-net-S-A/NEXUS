"""First-login onboarding endpoint.

Delivery Lead and Recruiter roles must complete a one-time role-specific
onboarding before the frontend unlocks the main shell. This module exposes
a minimal scoped job read plus a POST that branches on the caller's role,
persists the selections, and flips `users.profile_completed` to true.

Contract:
- Auth required (reuse the pre-onboarding `AuthenticatedUser` boundary).
- Idempotency: second call after completion returns 409.
- Wrong role (not DL / recruiter): 400.
- Missing/out-of-scope job ids: uniform 403 before mutation.
- Empty lists: accepted — flag still flips.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedUser, ensure_exclusive_role_configuration
from app.api.recruitment_access import job_scope_clause
from app.core.database import get_db
from app.models.client import Client
from app.models.job import Job, JobPriority, JobStatus
from app.models.job_collaborator import JobCollaborator
from app.models.user import User, UserRole
from app.schemas.onboarding import (
    OnboardingJobOption,
    OnboardingJobsResponse,
    OnboardingPayloadDL,
    OnboardingPayloadRecruiter,
    OnboardingResponse,
)
from app.schemas.user import UserResponse
from app.services.access_scope import ScopeKind, resolve_dashboard_scope
from app.services.onboarding_access import onboarding_persona_for_user

router = APIRouter()
_ONBOARDING_JOB_LIMIT = 200


def _require_incomplete_onboarding_persona(user: User) -> UserRole:
    ensure_exclusive_role_configuration(user)
    persona = onboarding_persona_for_user(user)
    if persona is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Role '{user.role.value}' does not require onboarding",
        )
    if user.profile_completed:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Onboarding already completed",
        )
    return persona


async def require_onboarding_user(
    current_user: AuthenticatedUser,
) -> User:
    """Raw-auth boundary limited to an incomplete DL/recruiter onboarding."""

    _require_incomplete_onboarding_persona(current_user)
    return current_user


OnboardingUser = Annotated[User, Depends(require_onboarding_user)]


def _apply_delivery_lead_onboarding_scope(query, allowed_client_ids):
    """Apply the resolved all-client DL boundary; empty means deny-all."""

    return query.where(Job.client_id.in_(sorted(allowed_client_ids) or [-1]))


async def _scoped_onboarding_jobs_query(
    db: AsyncSession,
    user: User,
    persona: UserRole,
):
    """Canonical read/write scope shared by onboarding GET and POST."""

    query = select(Job).where(
        Job.status == JobStatus.published,
        Job.client_id.is_not(None),
    )
    if persona is UserRole.delivery_lead:
        scope = await resolve_dashboard_scope(user, db)
        if scope.kind is not ScopeKind.delivery_clients or scope.user_id != user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Invalid Delivery Lead onboarding scope",
            )
        return _apply_delivery_lead_onboarding_scope(
            query,
            scope.allowed_client_ids,
        )
    if persona is UserRole.recruiter:
        return query.where(job_scope_clause(user, Job.id))
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Unsupported onboarding persona",
    )


async def _load_selected_scoped_jobs(
    db: AsyncSession,
    user: User,
    persona: UserRole,
    job_ids: list[int],
) -> dict[int, Job]:
    """Resolve every selected id inside the same scope used by onboarding GET."""

    requested = set(job_ids)
    if not requested:
        return {}
    query = await _scoped_onboarding_jobs_query(db, user, persona)
    jobs = list((await db.execute(query.where(Job.id.in_(requested)))).scalars().all())
    by_id = {job.id: job for job in jobs}
    if set(by_id) != requested:
        # Missing and foreign ids deliberately share one response so this raw
        # pre-onboarding endpoint cannot be used for job enumeration.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="One or more selected jobs is outside onboarding scope",
        )
    return by_id


async def _apply_dl_onboarding(
    db: AsyncSession,
    payload_raw: dict,
    user: User,
    persona: UserRole,
) -> OnboardingPayloadDL:
    payload = OnboardingPayloadDL.model_validate(payload_raw)
    scoped_jobs = await _load_selected_scoped_jobs(
        db,
        user,
        persona,
        payload.priority_job_ids + payload.needs_sourcing_job_ids,
    )

    for job_id in set(payload.priority_job_ids):
        scoped_jobs[job_id].priority = JobPriority.high
    for job_id in set(payload.needs_sourcing_job_ids):
        scoped_jobs[job_id].needs_sourcing = True

    return payload


async def _apply_recruiter_onboarding(
    db: AsyncSession,
    payload_raw: dict,
    user: User,
    persona: UserRole,
) -> OnboardingPayloadRecruiter:
    payload = OnboardingPayloadRecruiter.model_validate(payload_raw)
    await _load_selected_scoped_jobs(
        db,
        user,
        persona,
        payload.active_job_ids,
    )

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


@router.get(
    "/me/onboarding/jobs",
    response_model=OnboardingJobsResponse,
)
async def list_onboarding_jobs(
    current_user: OnboardingUser,
    db: AsyncSession = Depends(get_db),
) -> OnboardingJobsResponse:
    """Minimal, scoped job list available before onboarding is complete."""

    persona = _require_incomplete_onboarding_persona(current_user)
    query = await _scoped_onboarding_jobs_query(db, current_user, persona)
    total = int(
        (await db.execute(select(func.count()).select_from(query.subquery()))).scalar()
        or 0
    )
    rows = (
        await db.execute(
            query.join(Client, Client.id == Job.client_id)
            .add_columns(
                func.coalesce(
                    func.nullif(Client.display_name, ""),
                    Client.name,
                ).label("client_name")
            )
            .order_by(Job.created_at.desc(), Job.id.desc())
            .limit(_ONBOARDING_JOB_LIMIT)
        )
    ).all()
    return OnboardingJobsResponse(
        items=[
            OnboardingJobOption(
                id=job.id,
                title=job.title,
                client_name=client_name,
                location=job.location,
                status=job.status,
                seniority=job.seniority,
            )
            for job, client_name in rows
        ],
        total=total,
    )


@router.post(
    "/me/onboarding",
    response_model=OnboardingResponse,
    status_code=status.HTTP_200_OK,
)
async def complete_onboarding(
    request: Request,
    current_user: OnboardingUser,
    db: AsyncSession = Depends(get_db),
):
    """Submit role-specific onboarding payload and flip `profile_completed`.

    Body shape depends on the canonical persona from all user roles:
    - `delivery_lead` → `OnboardingPayloadDL`
    - `recruiter` → `OnboardingPayloadRecruiter`

    Any other role is rejected — those users are pre-completed by migration
    0031 and should never hit this endpoint.
    """
    persona = _require_incomplete_onboarding_persona(current_user)
    payload_raw = await request.json()

    if persona is UserRole.delivery_lead:
        await _apply_dl_onboarding(
            db,
            payload_raw,
            current_user,
            persona,
        )
    elif persona is UserRole.recruiter:
        await _apply_recruiter_onboarding(
            db,
            payload_raw,
            current_user,
            persona,
        )

    current_user.profile_completed = True
    current_user.profile_completed_at = func.now()
    await db.flush()
    await db.refresh(current_user)
    return OnboardingResponse(user=UserResponse.model_validate(current_user))
