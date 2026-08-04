"""Canonical first-login onboarding persona selection.

Onboarding is an authorization boundary, so it must evaluate the complete
multi-role set rather than only ``users.role``. Delivery Lead takes precedence
over Recruiter for hybrids; Admin is exempt.
"""

from __future__ import annotations

from collections.abc import Iterable

from app.models.user import User, UserRole


def onboarding_persona_for_roles(
    roles: Iterable[UserRole | str],
) -> UserRole | None:
    values = {role.value if isinstance(role, UserRole) else str(role) for role in roles}
    if UserRole.admin.value in values:
        return None
    if UserRole.delivery_lead.value in values:
        return UserRole.delivery_lead
    if UserRole.recruiter.value in values:
        return UserRole.recruiter
    return None


def onboarding_persona_for_user(user: User) -> UserRole | None:
    return onboarding_persona_for_roles(user.get_all_roles())


def onboarding_persona_changed(
    previous_roles: Iterable[UserRole | str],
    next_roles: Iterable[UserRole | str],
) -> bool:
    """Whether a role transition introduces a new required onboarding flow."""

    previous = onboarding_persona_for_roles(previous_roles)
    next_persona = onboarding_persona_for_roles(next_roles)
    return next_persona is not None and next_persona != previous
