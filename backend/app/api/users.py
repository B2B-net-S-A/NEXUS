"""Lightweight user-directory endpoint for authenticated UI pickers.

Different from `/api/admin/users` (which returns activity stats and is admin-
only). This is a minimal, read-only listing that any logged-in user can call
to populate a recruiter/owner picker. Always excludes inactive accounts and
read-only (`user` role) viewers — neither is a legitimate job owner.
"""

from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User, UserRole
from app.api.deps import CurrentUser
from app.schemas.job import UserBrief

router = APIRouter()


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
