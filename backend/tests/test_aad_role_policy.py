"""Focused unit contracts for fail-closed authoritative AAD role mappings."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.activity import Activity
from app.models.user import User, UserRole
from app.services.aad_role_policy import (
    InvalidAadRoleMapping,
    fail_closed_invalid_aad_mapping,
    validate_aad_mapped_roles,
)


def test_validate_aad_roles_deduplicates_and_preserves_precedence() -> None:
    values, roles = validate_aad_mapped_roles(["delivery_lead", "tac", "delivery_lead"])

    assert values == ["delivery_lead", "tac"]
    assert roles == [UserRole.delivery_lead, UserRole.tac]


@pytest.mark.parametrize(
    ("values", "message"),
    [
        (["admin", "unknown-role"], "unknown NEXUS role"),
        (["finance", "recruiter"], "finance role must be exclusive"),
        (["user", "recruiter"], "user role must be exclusive"),
    ],
)
def test_validate_aad_roles_rejects_unknown_and_exclusive_hybrids(
    values: list[str],
    message: str,
) -> None:
    with pytest.raises(InvalidAadRoleMapping, match=message):
        validate_aad_mapped_roles(values)


@pytest.mark.asyncio
async def test_invalid_mapping_deactivates_bumps_version_audits_and_commits() -> None:
    user = User(
        id=17,
        email="stale-admin@example.com",
        name="Stale Admin",
        role=UserRole.admin,
        roles=[UserRole.admin.value],
        is_active=True,
        profile_completed=True,
        authorization_version=9,
    )
    db = MagicMock()
    db.commit = AsyncMock()

    await fail_closed_invalid_aad_mapping(
        db,
        user,
        actor_user_id=user.id,
        action="sso_aad_role_mapping_invalid",
        reason="AAD finance role must be exclusive",
        mapped_roles=["finance", "recruiter"],
    )

    assert user.is_active is False
    assert user.authorization_version == 10
    assert user.tokens_valid_after is not None
    activity = db.add.call_args.args[0]
    assert isinstance(activity, Activity)
    assert activity.action == "sso_aad_role_mapping_invalid"
    assert activity.details["previous_roles"] == ["admin"]
    assert activity.details["mapped_roles"] == ["finance", "recruiter"]
    db.commit.assert_awaited_once()
