"""Compatibility helpers for pre-cutover ``User`` test factories."""

from __future__ import annotations

from collections.abc import Iterable

from app.models.user import User, UserRole


def normalise_omitted_user_rollout_fields(values: Iterable[object]) -> None:
    """Fill only fields omitted by established-account test fixtures."""

    for value in values:
        if not isinstance(value, User):
            continue
        if "profile_completed" not in value.__dict__:
            value.profile_completed = True
        if "roles" not in value.__dict__:
            primary = value.role or UserRole.recruiter
            value.roles = [primary.value]
