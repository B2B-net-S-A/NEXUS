"""Fail-closed policy helpers for authoritative AAD role mappings."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity
from app.models.user import User, UserRole


class InvalidAadRoleMapping(ValueError):
    """Raised when matched AAD groups do not form a valid NEXUS role set."""


def validate_aad_mapped_roles(
    role_values: Iterable[str],
) -> tuple[list[str], list[UserRole]]:
    """Validate and deduplicate matched AAD roles while preserving precedence."""

    unique_values = list(dict.fromkeys(str(value) for value in role_values))
    if not unique_values:
        raise InvalidAadRoleMapping("AAD mapping produced an empty role set")

    valid_values = {role.value for role in UserRole}
    unknown = next(
        (value for value in unique_values if value not in valid_values),
        None,
    )
    if unknown is not None:
        raise InvalidAadRoleMapping(
            f"AAD mapping contains unknown NEXUS role {unknown!r}"
        )
    mapped_roles = [UserRole(value) for value in unique_values]

    exclusive = {
        UserRole.finance,
        UserRole.user,
    }.intersection(mapped_roles)
    if exclusive and len(mapped_roles) != 1:
        role_name = (
            UserRole.finance.value
            if UserRole.finance in exclusive
            else UserRole.user.value
        )
        raise InvalidAadRoleMapping(f"AAD {role_name} role must be exclusive")

    return unique_values, mapped_roles


async def fail_closed_invalid_aad_mapping(
    db: AsyncSession,
    user: User,
    *,
    actor_user_id: int,
    action: str,
    reason: str,
    mapped_roles: Iterable[str] = (),
    details: Mapping[str, Any] | None = None,
) -> None:
    """Deactivate and persist invalidation before an error redirect/exception.

    Callers return an OAuth error redirect or raise ``HTTPException`` immediately
    afterwards. The explicit commit is required for the latter because the
    request-scoped DB dependency rolls back when an exception escapes.
    """

    previous_version = int(user.authorization_version or 0)
    previous_active = bool(user.is_active)
    previous_roles = sorted(role.value for role in user.get_all_roles())

    user.is_active = False
    user.authorization_version = previous_version + 1
    user.tokens_valid_after = datetime.now(timezone.utc)

    audit_details: dict[str, Any] = {
        "target_email": user.email,
        "reason": reason[:500],
        "mapped_roles": list(mapped_roles),
        "previous_roles": previous_roles,
        "previous_is_active": previous_active,
        "previous_authorization_version": previous_version,
        "new_authorization_version": user.authorization_version,
    }
    if details:
        audit_details.update(details)

    db.add(
        Activity(
            entity_type="user",
            entity_id=user.id,
            action=action,
            user_id=actor_user_id,
            details=audit_details,
        )
    )
    await db.commit()
