"""Lightweight user-directory endpoint for authenticated UI pickers.

Different from `/api/admin/users` (which returns activity stats and is admin-
only). This is a minimal, read-only listing that any logged-in user can call
to populate a recruiter/owner picker. Always excludes inactive accounts and
read-only (`user` role) viewers — neither is a legitimate job owner.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole
from app.api.deps import OperationalUser, CurrentUser
from app.schemas.job import UserBrief

router = APIRouter()


# ── Preferences schemas ────────────────────────────────────────────────────


class UserPreferencesUpdate(BaseModel):
    """Patch body for `/me/preferences`. All fields optional — pass only the
    ones you want to change."""

    kpi_coach_enabled: Optional[bool] = Field(
        default=None,
        description="Włącza/wyłącza in-app coaching KPI (praise + remind + EOD).",
    )


class UserPreferencesResponse(BaseModel):
    kpi_coach_enabled: bool


# Roles that can meaningfully own or collaborate on a job. `user` (viewer)
# is deliberately excluded — viewers should never appear in an owner picker.
_DEFAULT_ROLES = [
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.tac,
    UserRole.recruiter,
    UserRole.sourcer,
]


@router.get("", response_model=List[UserBrief])
async def list_users(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    roles: Optional[List[UserRole]] = Query(
        None,
        description=(
            "Filter by role. Repeat the param for multiple values "
            "(e.g. `?roles=recruiter&roles=tac`). Defaults to ownership-"
            "eligible roles (excludes read-only viewers)."
        ),
    ),
    q: Optional[str] = Query(None, description="Case-insensitive match on name/email."),
):
    """Directory listing for owner/collaborator pickers."""
    target_roles = roles if roles else _DEFAULT_ROLES
    effective_role_filter = or_(
        User.role.in_(target_roles),
        *(User.roles.contains([role.value]) for role in target_roles),
    )
    query = (
        select(User)
        .where(User.is_active.is_(True))
        .where(effective_role_filter)
        .order_by(User.name)
    )
    if q:
        needle = f"%{q}%"
        query = query.where((User.name.ilike(needle)) | (User.email.ilike(needle)))
    result = await db.execute(query)
    return [UserBrief.model_validate(u) for u in result.scalars().all()]


@router.get("/mentionable", response_model=List[UserBrief])
async def list_mentionable_users(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    job_id: Optional[int] = Query(
        None,
        description=(
            "Jeśli podane: zwraca tylko members tego projektu (job-scope). "
            "Używane gdy mention dotyczy notatki/chatu związanego z konkretnym "
            "projektem."
        ),
    ),
    candidate_id: Optional[int] = Query(
        None,
        description=(
            "Jeśli podane: zwraca tylko members chatu kandydata. Używane przez "
            "candidate chat. Job_id ma pierwszeństwo gdy oba są podane."
        ),
    ),
    q: Optional[str] = Query(None, description="Case-insensitive match on name/email."),
    include_inactive: bool = Query(
        False,
        description=(
            "Jeśli True — zwraca też nieaktywnych userów (Faza A: 131 userów "
            "zaimportowanych z Traffit jako disabled accounts). Używane gdy "
            "renderujemy historyczne notatki i chcemy pokazać autora któremu "
            "konto wygasło."
        ),
    ),
):
    """Lista userów dostępnych do @mention.

    Trzy tryby (mutually exclusive — pierwszy match wygrywa):
      job_id       → members projektu (przez list_job_member_ids)
      candidate_id → members chatu kandydata (przez list_candidate_chat_member_ids)
      brak ID      → wszyscy aktywni z rolą != `user` (default _DEFAULT_ROLES)

    Domyślnie filtruje `is_active=True`. Z `include_inactive=true` rozszerza
    o disabled userów (np. importowani z Traffit w Faza A migracji).
    Frontend `MentionTextarea` cache'uje przez react-query (`staleTime: 60s`).
    """
    active_clause = User.is_active.is_(True)

    if job_id is not None:
        from app.services.job_membership import list_job_member_ids

        member_ids = await list_job_member_ids(db, job_id)
        if not member_ids:
            return []
        q_stmt = select(User).where(User.id.in_(member_ids))
        if not include_inactive:
            q_stmt = q_stmt.where(active_clause)
        rows = await db.execute(q_stmt.order_by(User.name))
        users = list(rows.scalars().all())
    elif candidate_id is not None:
        from app.services.candidate_membership import (
            list_candidate_chat_member_ids,
        )

        member_ids = await list_candidate_chat_member_ids(db, candidate_id)
        if not member_ids:
            return []
        q_stmt = select(User).where(User.id.in_(member_ids))
        if not include_inactive:
            q_stmt = q_stmt.where(active_clause)
        rows = await db.execute(q_stmt.order_by(User.name))
        users = list(rows.scalars().all())
    else:
        q_stmt = select(User).where(
            or_(
                User.role.in_(_DEFAULT_ROLES),
                *(User.roles.contains([role.value]) for role in _DEFAULT_ROLES),
            )
        )
        if not include_inactive:
            q_stmt = q_stmt.where(active_clause)
        rows = await db.execute(q_stmt.order_by(User.name))
        users = list(rows.scalars().all())

    if q:
        needle = q.lower()
        users = [
            u
            for u in users
            if needle in (u.email or "").lower() or needle in (u.name or "").lower()
        ]
    return [UserBrief.model_validate(u) for u in users]


# ── Preferences ────────────────────────────────────────────────────────────


@router.get("/me/preferences", response_model=UserPreferencesResponse)
async def get_my_preferences(current_user: CurrentUser):
    """Zwraca aktualne preferencje bieżącego użytkownika."""
    return UserPreferencesResponse(kpi_coach_enabled=current_user.kpi_coach_enabled)


@router.patch("/me/preferences", response_model=UserPreferencesResponse)
async def update_my_preferences(
    payload: UserPreferencesUpdate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Częściowa aktualizacja preferencji bieżącego użytkownika.

    Obsługuje dziś tylko `kpi_coach_enabled`. W przyszłości rozszerzymy o
    kolejne toggle (slack_channel, email_digest itp.).
    """
    changed = False
    if payload.kpi_coach_enabled is not None:
        current_user.kpi_coach_enabled = payload.kpi_coach_enabled
        changed = True

    if changed:
        await db.commit()
        await db.refresh(current_user)

    return UserPreferencesResponse(kpi_coach_enabled=current_user.kpi_coach_enabled)
