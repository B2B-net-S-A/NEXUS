"""Transactional protection for the active administrator set."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import HTTPException, status
from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole


# Process-wide PostgreSQL advisory key reserved for serialising changes that
# could remove the final active administrator. Parameterising it keeps the lock
# visible to database observability without embedding a magic literal in SQL.
_ACTIVE_ADMIN_MEMBERSHIP_LOCK_KEY = 72_622_401


async def protect_active_admin_membership(
    db: AsyncSession,
    *,
    actor_id: int | None,
    target: User,
    next_roles: Iterable[str],
    next_active: bool,
    protect_self: bool = True,
) -> None:
    """Reject a change that removes self or the final active administrator.

    The caller must first lock ``target`` with ``SELECT ... FOR UPDATE``.  The
    PostgreSQL advisory transaction lock serializes changes to *different*
    administrator rows, which a row lock alone cannot do.

    ``protect_self=False`` is reserved for an authoritative identity provider:
    AAD may demote the signing-in administrator, but only while another active
    administrator remains available as the break-glass operator.
    """

    current_roles = {role.value for role in target.get_all_roles()}
    proposed_roles = set(next_roles)
    removes_active_admin = (
        target.is_active
        and UserRole.admin.value in current_roles
        and (not next_active or UserRole.admin.value not in proposed_roles)
    )
    if not removes_active_admin:
        return
    if protect_self and actor_id == target.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own administrator access",
        )

    bind = db.get_bind()
    if bind.dialect.name == "postgresql":
        await db.execute(
            text("SELECT pg_advisory_xact_lock(:lock_key)"),
            {"lock_key": _ACTIVE_ADMIN_MEMBERSHIP_LOCK_KEY},
        )
    remaining = await db.scalar(
        select(func.count(User.id)).where(
            User.id != target.id,
            User.is_active.is_(True),
            or_(
                User.role == UserRole.admin,
                User.roles.contains([UserRole.admin.value]),
            ),
        )
    )
    if int(remaining or 0) == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="At least one active administrator must remain",
        )
