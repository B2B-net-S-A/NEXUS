"""Admin API contract for configurable role access and user exceptions."""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, func, select

from app.api.admin_section_permissions import (
    RolePermissionUpdate,
    update_role_section_permissions,
)
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token, hash_password
from app.models.section_permission import (
    RbacPermissionAudit,
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def permission_target() -> AsyncIterator[dict[str, object]]:
    unique = uuid.uuid4().hex[:10]
    email = f"pytest-section-permission-{unique}@example.com"
    password = f"Section_{unique}_Pass!"
    async with AsyncSessionLocal() as db:
        user = User(
            email=email,
            password_hash=hash_password(password),
            name="Permission Target",
            role=UserRole.recruiter,
            roles=[UserRole.recruiter.value],
            is_active=True,
            email_verified=True,
            profile_completed=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        user_id = user.id

    yield {"id": user_id, "email": email, "password": password}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RbacPermissionAudit).where(
                RbacPermissionAudit.target_kind == "user",
                RbacPermissionAudit.target_key == str(user_id),
            )
        )
        await db.execute(
            delete(UserSectionOverride).where(UserSectionOverride.user_id == user_id)
        )
        await db.execute(
            delete(UserActionOverride).where(UserActionOverride.user_id == user_id)
        )
        target = await db.scalar(select(User).where(User.id == user_id))
        if target is not None:
            await db.delete(target)
        await db.commit()


async def test_user_override_is_versioned_audited_and_returned_in_auth_snapshot(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: dict[str, object],
) -> None:
    policy = await app_client.get(
        "/api/admin/section-permissions", headers=app_auth_headers
    )
    assert policy.status_code == 200, policy.text
    revision = policy.json()["revision"]
    admin_row = next(row for row in policy.json()["roles"] if row["role"] == "admin")
    assert admin_row["locked"] is True
    assert admin_row["permissions"]["system_admin"] == "write"
    assert admin_row["action_permissions"]["b2b_contract_generator"] == "manage"

    target_id = int(permission_target["id"])
    grant = await app_client.put(
        f"/api/admin/section-permissions/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "changes": [{"section": "delivery", "access": "read"}],
        },
    )
    assert grant.status_code == 200, grant.text
    assert grant.json()["revision"] == revision + 1
    assert grant.json()["invalidated_users"] == 1

    stale = await app_client.put(
        f"/api/admin/section-permissions/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "changes": [{"section": "delivery", "access": "write"}],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_section_policy"

    users = await app_client.get(
        "/api/admin/section-permissions/users",
        headers=app_auth_headers,
        params={"search": permission_target["email"]},
    )
    assert users.status_code == 200, users.text
    [row] = users.json()["users"]
    assert row["overrides"]["delivery"] == "read"
    assert row["effective_permissions"]["delivery"] == "read"
    assert row["effective_action_permissions"]["b2b_contract_generator"] == "manage"

    login = await app_client.post(
        "/api/auth/login",
        json={
            "email": permission_target["email"],
            "password": permission_target["password"],
        },
    )
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    assert decode_token(access_token)["sa"]["delivery"] == "read"
    me = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["effective_section_access"]["delivery"] == "read"
    assert me.json()["effective_action_access"]["b2b_contract_generator"] == "manage"

    impersonation = await app_client.post(
        f"/api/admin/impersonate/{target_id}", headers=app_auth_headers
    )
    assert impersonation.status_code == 200, impersonation.text
    impersonated_profile = impersonation.json()
    target_profile = me.json()
    for field in (
        "id",
        "email",
        "role",
        "roles",
        "capabilities",
        "analytics_capabilities",
        "available_dashboard_presets",
        "default_dashboard_preset",
        "data_scope",
        "effective_section_access",
        "effective_action_access",
        "analytics_v1_mode",
    ):
        assert impersonated_profile[field] == target_profile[field]

    async with AsyncSessionLocal() as db:
        target = await db.scalar(select(User).where(User.id == target_id))
        assert target is not None and target.authorization_version == 2
        audit = await db.scalar(
            select(RbacPermissionAudit)
            .where(
                RbacPermissionAudit.target_kind == "user",
                RbacPermissionAudit.target_key == str(target_id),
            )
            .order_by(RbacPermissionAudit.id.desc())
        )
        assert audit is not None
        assert audit.revision == revision + 1
        assert audit.before == {}
        assert audit.after == {"delivery": "read"}

    inherit = await app_client.put(
        f"/api/admin/section-permissions/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision + 1,
            "changes": [{"section": "delivery", "access": "inherit"}],
        },
    )
    assert inherit.status_code == 200, inherit.text


async def test_user_action_override_is_audited_and_returned_in_auth_snapshot(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: dict[str, object],
) -> None:
    policy = await app_client.get(
        "/api/admin/section-permissions", headers=app_auth_headers
    )
    assert policy.status_code == 200, policy.text
    revision = policy.json()["revision"]
    target_id = int(permission_target["id"])

    grant = await app_client.put(
        f"/api/admin/section-permissions/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "action_changes": [
                {
                    "action": "b2b_contract_generator",
                    "access": "generate",
                }
            ],
        },
    )
    assert grant.status_code == 200, grant.text
    assert grant.json() == {
        "revision": revision + 1,
        "changed": True,
        "invalidated_users": 1,
    }

    users = await app_client.get(
        "/api/admin/section-permissions/users",
        headers=app_auth_headers,
        params={"search": permission_target["email"]},
    )
    assert users.status_code == 200, users.text
    [row] = users.json()["users"]
    assert row["action_overrides"] == {"b2b_contract_generator": "generate"}
    assert row["inherited_action_permissions"] == {"b2b_contract_generator": "manage"}
    assert row["effective_action_permissions"] == {"b2b_contract_generator": "generate"}
    assert row["effective_permissions"]["finance"] == "none"

    login = await app_client.post(
        "/api/auth/login",
        json={
            "email": permission_target["email"],
            "password": permission_target["password"],
        },
    )
    assert login.status_code == 200, login.text
    access_token = login.json()["access_token"]
    me = await app_client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {access_token}"}
    )
    assert me.status_code == 200, me.text
    assert me.json()["effective_action_access"] == {
        "b2b_contract_generator": "generate"
    }
    assert me.json()["effective_section_access"]["finance"] == "none"

    generate = await app_client.post(
        "/api/b2b-generator/generate",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"role_id": 999999, "start_date": "2026-01-01"},
    )
    assert generate.status_code == 404, generate.text
    manage = await app_client.patch(
        "/api/b2b-generator/generated/999999",
        headers={"Authorization": f"Bearer {access_token}"},
        json={"client_name": "Blocked"},
    )
    assert manage.status_code == 403, manage.text
    assert manage.json()["detail"] == {
        "code": "action_access_denied",
        "action": "b2b_contract_generator",
        "required": "manage",
        "granted": "generate",
    }

    async with AsyncSessionLocal() as db:
        audit = await db.scalar(
            select(RbacPermissionAudit)
            .where(
                RbacPermissionAudit.target_kind == "user",
                RbacPermissionAudit.target_key == str(target_id),
            )
            .order_by(RbacPermissionAudit.id.desc())
        )
        assert audit is not None
        assert audit.revision == revision + 1
        assert audit.before == {}
        assert audit.after == {"action:b2b_contract_generator": "generate"}


async def test_technical_admin_access_cannot_be_delegated_or_overridden(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: dict[str, object],
) -> None:
    policy = await app_client.get(
        "/api/admin/section-permissions", headers=app_auth_headers
    )
    revision = policy.json()["revision"]

    role_change = await app_client.put(
        "/api/admin/section-permissions/roles",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "changes": [
                {
                    "role": "recruiter",
                    "section": "system_admin",
                    "access": "write",
                }
            ],
        },
    )
    assert role_change.status_code == 422

    user_change = await app_client.put(
        f"/api/admin/section-permissions/users/{permission_target['id']}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "changes": [{"section": "system_admin", "access": "write"}],
        },
    )
    assert user_change.status_code == 422


async def test_explicit_none_materializes_a_missing_role_row(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """A fail-closed gap must not be restored to a permissive default on boot."""

    role = UserRole.user.value
    section = "finance"
    key = f"{role}:{section}"
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RoleSectionPermission).where(
                RoleSectionPermission.role == role,
                RoleSectionPermission.section == section,
            )
        )
        await db.commit()

    policy = await app_client.get(
        "/api/admin/section-permissions", headers=app_auth_headers
    )
    assert policy.status_code == 200, policy.text
    revision = policy.json()["revision"]
    role_row = next(row for row in policy.json()["roles"] if row["role"] == role)
    assert role_row["permissions"][section] == "none"

    try:
        response = await app_client.put(
            "/api/admin/section-permissions/roles",
            headers=app_auth_headers,
            json={
                "revision": revision,
                "changes": [{"role": role, "section": section, "access": "none"}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["changed"] is True
        assert response.json()["revision"] == revision + 1

        async with AsyncSessionLocal() as db:
            restored = await db.scalar(
                select(RoleSectionPermission).where(
                    RoleSectionPermission.role == role,
                    RoleSectionPermission.section == section,
                )
            )
            assert restored is not None
            assert restored.access == "none"
            audit = await db.scalar(
                select(RbacPermissionAudit)
                .where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
                .order_by(RbacPermissionAudit.id.desc())
            )
            assert audit is not None
            assert audit.before == {key: "missing"}
            assert audit.after == {key: "none"}
    finally:
        async with AsyncSessionLocal() as db:
            restored = await db.scalar(
                select(RoleSectionPermission).where(
                    RoleSectionPermission.role == role,
                    RoleSectionPermission.section == section,
                )
            )
            if restored is None:
                db.add(
                    RoleSectionPermission(
                        role=role,
                        section=section,
                        access="none",
                    )
                )
            await db.execute(
                delete(RbacPermissionAudit).where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
            )
            await db.commit()


async def test_explicit_none_materializes_a_missing_role_action_row(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """A missing privileged-action row stays fail-closed until audited repair."""

    role = UserRole.user.value
    action = "b2b_contract_generator"
    key = f"{role}:action:{action}"
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RoleActionPermission).where(
                RoleActionPermission.role == role,
                RoleActionPermission.action == action,
            )
        )
        await db.commit()

    policy = await app_client.get(
        "/api/admin/section-permissions", headers=app_auth_headers
    )
    assert policy.status_code == 200, policy.text
    revision = policy.json()["revision"]
    role_row = next(row for row in policy.json()["roles"] if row["role"] == role)
    assert role_row["action_permissions"][action] == "none"

    try:
        response = await app_client.put(
            "/api/admin/section-permissions/roles",
            headers=app_auth_headers,
            json={
                "revision": revision,
                "action_changes": [{"role": role, "action": action, "access": "none"}],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["changed"] is True
        assert response.json()["revision"] == revision + 1

        async with AsyncSessionLocal() as db:
            restored = await db.scalar(
                select(RoleActionPermission).where(
                    RoleActionPermission.role == role,
                    RoleActionPermission.action == action,
                )
            )
            assert restored is not None
            assert restored.access == "none"
            audit = await db.scalar(
                select(RbacPermissionAudit)
                .where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
                .order_by(RbacPermissionAudit.id.desc())
            )
            assert audit is not None
            assert audit.before == {key: "missing"}
            assert audit.after == {key: "none"}
    finally:
        async with AsyncSessionLocal() as db:
            restored = await db.scalar(
                select(RoleActionPermission).where(
                    RoleActionPermission.role == role,
                    RoleActionPermission.action == action,
                )
            )
            if restored is None:
                db.add(
                    RoleActionPermission(
                        role=role,
                        action=action,
                        access="view",
                    )
                )
            else:
                restored.access = "view"
            await db.execute(
                delete(RbacPermissionAudit).where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
            )
            await db.commit()


async def test_policy_write_revalidates_admin_after_concurrent_demotion(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """A request authorized before demotion cannot mutate RBAC afterwards."""

    token = app_auth_headers["Authorization"].removeprefix("Bearer ")
    admin_id = int(decode_token(token)["sub"])
    async with AsyncSessionLocal() as stale_session:
        stale_admin = await stale_session.get(User, admin_id)
        assert stale_admin is not None and stale_admin.has_role(UserRole.admin)
        original_role = stale_admin.role
        original_roles = list(stale_admin.roles or [])
        original_active = stale_admin.is_active
        original_version = stale_admin.authorization_version
        original_floor = stale_admin.tokens_valid_after

        state = await stale_session.get(RbacPolicyState, 1)
        assert state is not None
        revision = state.revision
        audits_before = int(
            (
                await stale_session.scalar(
                    select(func.count(RbacPermissionAudit.id)).where(
                        RbacPermissionAudit.revision > revision
                    )
                )
            )
            or 0
        )

        async with AsyncSessionLocal() as concurrent_session:
            concurrent_admin = await concurrent_session.get(User, admin_id)
            assert concurrent_admin is not None
            concurrent_admin.role = UserRole.recruiter
            concurrent_admin.roles = [UserRole.recruiter.value]
            concurrent_admin.authorization_version += 1
            await concurrent_session.commit()

        try:
            payload = RolePermissionUpdate.model_validate(
                {
                    "revision": revision,
                    "changes": [
                        {"role": "user", "section": "finance", "access": "read"}
                    ],
                }
            )
            with pytest.raises(HTTPException) as exc_info:
                await update_role_section_permissions(
                    payload=payload,
                    admin=stale_admin,
                    db=stale_session,
                )
            assert exc_info.value.status_code == 403
            assert exc_info.value.detail["code"] == "administrator_access_changed"
            await stale_session.rollback()

            async with AsyncSessionLocal() as verify_session:
                current_state = await verify_session.get(RbacPolicyState, 1)
                assert current_state is not None
                assert current_state.revision == revision
                audits_after = int(
                    (
                        await verify_session.scalar(
                            select(func.count(RbacPermissionAudit.id)).where(
                                RbacPermissionAudit.revision > revision
                            )
                        )
                    )
                    or 0
                )
                assert audits_after == audits_before
        finally:
            await stale_session.rollback()
            async with AsyncSessionLocal() as restore_session:
                current_admin = await restore_session.get(User, admin_id)
                assert current_admin is not None
                current_admin.role = original_role
                current_admin.roles = original_roles
                current_admin.is_active = original_active
                current_admin.authorization_version = original_version
                current_admin.tokens_valid_after = original_floor
                await restore_session.commit()


async def test_admin_cannot_remove_or_deactivate_own_administrator_access(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    token = app_auth_headers["Authorization"].removeprefix("Bearer ")
    admin_id = int(decode_token(token)["sub"])

    demote = await app_client.put(
        f"/api/admin/users/{admin_id}",
        headers=app_auth_headers,
        json={"role": "recruiter", "roles": ["recruiter"]},
    )
    assert demote.status_code == 400
    assert "own administrator access" in demote.json()["detail"]

    deactivate = await app_client.put(
        f"/api/admin/users/{admin_id}",
        headers=app_auth_headers,
        json={"is_active": False},
    )
    assert deactivate.status_code == 400
