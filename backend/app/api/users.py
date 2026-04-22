"""Lightweight user-directory endpoint for authenticated UI pickers.

Different from `/api/admin/users` (which returns activity stats and is admin-
only). This is a minimal, read-only listing that any logged-in user can call
to populate a recruiter/owner picker. Always excludes inactive accounts and
read-only (`user` role) viewers — neither is a legitimate job owner.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole
from app.api.deps import CurrentUser
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
    current_user: CurrentUser,
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
    query = (
        select(User)
        .where(User.is_active.is_(True))
        .where(User.role.in_(target_roles))
        .order_by(User.name)
    )
    if q:
        needle = f"%{q}%"
        query = query.where((User.name.ilike(needle)) | (User.email.ilike(needle)))
    result = await db.execute(query)
    return [UserBrief.model_validate(u) for u in result.scalars().all()]


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
