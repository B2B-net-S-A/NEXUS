"""Admin API contract for role permissions and per-user grants.

Ekran Ustawienia → Zespół i dostęp → „Osoby i role”; kontrakt odpowiedzi:
``docs/permissions-nine-switches-contract.md`` §7. Kształt liczony bez bazy
pilnuje ``test_admin_permission_payloads.py`` — tu zapis, audyt i skutek zmiany
dla zalogowanej osoby.
"""

from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from typing import AsyncIterator

import pytest
import pytest_asyncio
from fastapi import HTTPException
from httpx import AsyncClient
from sqlalchemy import delete, func, or_, select

from app.api.admin_section_permissions import (
    RolePermissionUpdate,
    update_role_section_permissions,
)
from app.core.database import AsyncSessionLocal
from app.core.security import decode_token, hash_password
from app.models.critical_event import CriticalEvent
from app.models.section_permission import (
    RbacPermissionAudit,
    RbacPolicyState,
    RoleActionPermission,
    RoleSectionPermission,
    UserActionOverride,
    UserSectionOverride,
)
from app.models.user import User, UserRole
from app.services import permission_catalog as catalog


pytestmark = pytest.mark.asyncio

PANEL = "/api/admin/section-permissions"
_EVENT_TYPES = ("rbac.role_permissions", "rbac.user_permissions")

Account = dict[str, object]


@pytest_asyncio.fixture
async def make_account() -> AsyncIterator[Callable[[UserRole], Awaitable[Account]]]:
    created: list[int] = []

    async def _make(role: UserRole) -> Account:
        unique = uuid.uuid4().hex[:10]
        email = f"pytest-section-permission-{unique}@example.com"
        password = f"Section_{unique}_Pass!"
        async with AsyncSessionLocal() as db:
            user = User(
                email=email,
                password_hash=hash_password(password),
                name="Permission Target",
                role=role,
                roles=[role.value],
                is_active=True,
                email_verified=True,
                profile_completed=True,
            )
            db.add(user)
            await db.commit()
            await db.refresh(user)
            created.append(user.id)
            return {"id": user.id, "email": email, "password": password}

    yield _make

    async with AsyncSessionLocal() as db:
        for user_id in created:
            await db.execute(
                delete(RbacPermissionAudit).where(
                    RbacPermissionAudit.target_kind == "user",
                    RbacPermissionAudit.target_key == str(user_id),
                )
            )
            await db.execute(
                delete(CriticalEvent).where(
                    CriticalEvent.entity_type == "user",
                    CriticalEvent.entity_id == user_id,
                    CriticalEvent.event_type.in_(_EVENT_TYPES),
                )
            )
            await db.execute(
                delete(UserSectionOverride).where(
                    UserSectionOverride.user_id == user_id
                )
            )
            await db.execute(
                delete(UserActionOverride).where(UserActionOverride.user_id == user_id)
            )
            target = await db.scalar(select(User).where(User.id == user_id))
            if target is not None:
                await db.delete(target)
        await db.commit()


@pytest_asyncio.fixture
async def permission_target(
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> Account:
    return await make_account(UserRole.recruiter)


async def _snapshot(client: AsyncClient, headers: dict[str, str]) -> dict:
    response = await client.get(PANEL, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


async def _login(client: AsyncClient, account: Account) -> dict[str, str]:
    response = await client.post(
        "/api/auth/login",
        json={"email": account["email"], "password": account["password"]},
    )
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


async def _last_event_id() -> int:
    async with AsyncSessionLocal() as db:
        return int((await db.scalar(select(func.max(CriticalEvent.id)))) or 0)


async def _drop_role_traces(*, after_event_id: int, after_revision: int) -> None:
    """Ślady zmian ROLI z jednego testu — baza jest wspólna dla całego przebiegu."""

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(CriticalEvent).where(
                CriticalEvent.id > after_event_id,
                CriticalEvent.event_type == "rbac.role_permissions",
            )
        )
        await db.execute(
            delete(RbacPermissionAudit).where(
                RbacPermissionAudit.target_kind == "role",
                RbacPermissionAudit.revision > after_revision,
            )
        )
        await db.commit()


async def _role_action_rows(role: str) -> dict[str, tuple[str, int | None]]:
    async with AsyncSessionLocal() as db:
        rows = (
            await db.scalars(
                select(RoleActionPermission).where(RoleActionPermission.role == role)
            )
        ).all()
        return {row.action: (row.access, row.updated_by) for row in rows}


async def _restore_role_action_rows(
    role: str, original: dict[str, tuple[str, int | None]]
) -> None:
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RoleActionPermission).where(RoleActionPermission.role == role)
        )
        for action, (access, updated_by) in original.items():
            db.add(
                RoleActionPermission(
                    role=role, action=action, access=access, updated_by=updated_by
                )
            )
        await db.commit()


# ── Odczyt: katalog i role ───────────────────────────────────────────────────


async def test_role_snapshot_carries_the_catalogue_and_derived_sections(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    policy = await _snapshot(app_client, app_auth_headers)

    assert policy["derived_sections"] == ["delivery", "finance"]
    assert [group["key"] for group in policy["permission_groups"]] == [
        "clients_contracts",
        "recruitment",
        "money",
    ]
    assert [item["key"] for item in policy["permissions"]] == list(catalog.KEYS)
    assert policy["permissions"][0]["label"] == catalog.label("delivery_view")
    assert set(policy["actions"]) == {"b2b_contract_generator", *catalog.KEYS}

    roles = {row["role"]: row for row in policy["roles"]}
    assert {role for role, row in roles.items() if not row["grantable"]} == {
        "admin",
        "user",
        "trainee",
    }
    finance = roles["finance"]
    assert finance["named"]["contracts_orders_edit"]["granted"] is True
    assert finance["named"]["delivery_view"]["effective"] is True
    assert "contracts_orders_edit" in finance["named"]["delivery_view"]["implied_by"]
    # Sekcje Delivery i Finanse są wyliczone z uprawnień, nie przepisane z wierszy.
    assert finance["permissions"]["delivery"] == "write"
    assert finance["permissions"]["finance"] == "write"
    tac = roles["tac"]
    assert tac["named"]["b2b_signature_confirmation"]["granted"] is False
    assert tac["permissions"]["delivery"] == "none"

    async with AsyncSessionLocal() as db:
        expected = await db.scalar(
            select(func.count(User.id)).where(
                User.is_active.is_(True),
                or_(User.role == UserRole.finance, User.roles.contains(["finance"])),
            )
        )
    assert finance["users_count"] == expected

    await make_account(UserRole.finance)
    after = await _snapshot(app_client, app_auth_headers)
    counted = next(row for row in after["roles"] if row["role"] == "finance")
    assert counted["users_count"] == expected + 1


# ── Osoba: nadanie, audyt, migawka w tokenie ─────────────────────────────────


async def test_personal_grant_is_versioned_audited_and_returned_in_auth_snapshot(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: Account,
) -> None:
    policy = await _snapshot(app_client, app_auth_headers)
    revision = policy["revision"]
    admin_row = next(row for row in policy["roles"] if row["role"] == "admin")
    assert admin_row["locked"] is True
    assert admin_row["permissions"]["system_admin"] == "write"
    assert admin_row["action_permissions"]["b2b_contract_generator"] == "manage"

    target_id = int(permission_target["id"])
    grant = await app_client.put(
        f"{PANEL}/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "action_changes": [{"action": "delivery_view", "access": "manage"}],
        },
    )
    assert grant.status_code == 200, grant.text
    assert grant.json() == {
        "revision": revision + 1,
        "changed": True,
        "invalidated_users": 1,
    }

    stale = await app_client.put(
        f"{PANEL}/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision,
            "action_changes": [{"action": "clients_edit", "access": "manage"}],
        },
    )
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "stale_section_policy"

    users = await app_client.get(
        f"{PANEL}/users",
        headers=app_auth_headers,
        params={"search": permission_target["email"]},
    )
    assert users.status_code == 200, users.text
    [row] = users.json()["users"]
    assert row["action_overrides"] == {"delivery_view": "manage"}
    # Podgląd nadany osobie otwiera sekcję Delivery do odczytu — sama rola nie.
    assert row["inherited_permissions"]["delivery"] == "none"
    assert row["effective_permissions"]["delivery"] == "read"
    assert row["inherited_action_permissions"]["delivery_view"] == "none"
    assert row["effective_action_permissions"]["delivery_view"] == "manage"
    assert row["effective_action_permissions"]["b2b_contract_generator"] == "manage"

    detail = await app_client.get(
        f"{PANEL}/users/{target_id}", headers=app_auth_headers
    )
    assert detail.status_code == 200, detail.text
    assert detail.json() == {
        "revision": revision + 1,
        "user": {
            "user_id": target_id,
            "name": "Permission Target",
            "role": "recruiter",
            "roles": ["recruiter"],
            "locked": False,
            "grantable": True,
            "role_permissions": [],
            "grants": ["delivery_view"],
            "restrictions": [],
            "effective": ["delivery_view"],
            "legacy_section_caps": {},
        },
    }

    listing = await app_client.get("/api/admin/users", headers=app_auth_headers)
    assert listing.status_code == 200, listing.text
    account = next(item for item in listing.json() if item["id"] == target_id)
    assert account["extra_permissions"] == ["delivery_view"]

    target_headers = await _login(app_client, permission_target)
    access_token = target_headers["Authorization"].removeprefix("Bearer ")
    assert decode_token(access_token)["sa"]["delivery"] == "read"
    me = await app_client.get("/api/auth/me", headers=target_headers)
    assert me.status_code == 200, me.text
    assert me.json()["effective_section_access"]["delivery"] == "read"
    assert me.json()["effective_action_access"]["delivery_view"] == "manage"
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
        assert audit.after == {"action:delivery_view": "manage"}
        event = await db.scalar(
            select(CriticalEvent)
            .where(
                CriticalEvent.event_type == "rbac.user_permissions",
                CriticalEvent.entity_id == target_id,
            )
            .order_by(CriticalEvent.id.desc())
        )
        assert event is not None
        assert event.entity_type == "user"
        assert event.outcome == "executed"
        assert event.reason == "Nadano: „Klienci, kontrakty i zamówienia: podgląd”."
        assert event.details == {
            "revision": revision + 1,
            "changes": {"delivery_view": {"from": "inherit", "to": "manage"}},
        }

    inherit = await app_client.put(
        f"{PANEL}/users/{target_id}",
        headers=app_auth_headers,
        json={
            "revision": revision + 1,
            "action_changes": [{"action": "delivery_view", "access": "inherit"}],
        },
    )
    assert inherit.status_code == 200, inherit.text
    cleared = await app_client.get(
        f"{PANEL}/users/{target_id}", headers=app_auth_headers
    )
    assert cleared.json()["user"]["grants"] == []
    assert cleared.json()["user"]["effective"] == []


async def test_user_action_override_is_audited_and_returned_in_auth_snapshot(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: Account,
) -> None:
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]
    target_id = int(permission_target["id"])

    grant = await app_client.put(
        f"{PANEL}/users/{target_id}",
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
        f"{PANEL}/users",
        headers=app_auth_headers,
        params={"search": permission_target["email"]},
    )
    assert users.status_code == 200, users.text
    [row] = users.json()["users"]
    assert row["action_overrides"] == {"b2b_contract_generator": "generate"}
    assert row["inherited_action_permissions"]["b2b_contract_generator"] == "manage"
    assert row["effective_action_permissions"]["b2b_contract_generator"] == "generate"
    assert row["effective_permissions"]["finance"] == "none"

    target_headers = await _login(app_client, permission_target)
    me = await app_client.get("/api/auth/me", headers=target_headers)
    assert me.status_code == 200, me.text
    assert me.json()["effective_action_access"]["b2b_contract_generator"] == "generate"
    assert me.json()["effective_section_access"]["finance"] == "none"

    generate = await app_client.post(
        "/api/b2b-generator/generate",
        headers=target_headers,
        json={"role_id": 999999, "start_date": "2026-01-01"},
    )
    assert generate.status_code == 404, generate.text
    manage = await app_client.patch(
        "/api/b2b-generator/generated/999999",
        headers=target_headers,
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


async def test_signature_and_generator_are_set_independently_for_a_person(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: Account,
) -> None:
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]
    target_url = f"{PANEL}/users/{permission_target['id']}"
    response = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": revision,
            "action_changes": [
                {"action": "b2b_contract_generator", "access": "view"},
                {"action": "b2b_signature_confirmation", "access": "manage"},
            ],
        },
    )
    assert response.status_code == 200, response.text
    users = await app_client.get(
        f"{PANEL}/users",
        headers=app_auth_headers,
        params={"search": permission_target["email"]},
    )
    [user] = users.json()["users"]
    effective = user["effective_action_permissions"]
    assert effective["b2b_contract_generator"] == "view"
    assert effective["b2b_signature_confirmation"] == "manage"
    # Podpis nie pociąga żadnego innego uprawnienia ani sekcji.
    assert effective["delivery_view"] == "none"
    assert user["effective_permissions"]["delivery"] == "none"
    assert user["effective_permissions"]["finance"] == "none"

    # Uprawnienia osoby tylko dodają: nadanie zdejmuje się przez „inherit”.
    revoke = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": response.json()["revision"],
            "action_changes": [
                {"action": "b2b_signature_confirmation", "access": "none"},
            ],
        },
    )
    assert revoke.status_code == 422, revoke.text
    assert revoke.json()["detail"]["code"] == "additive_only"
    lifted = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": response.json()["revision"],
            "action_changes": [
                {"action": "b2b_signature_confirmation", "access": "inherit"},
            ],
        },
    )
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["changed"] is True


async def test_person_permissions_only_add_and_derived_sections_cannot_be_set(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: Account,
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]
    target_id = int(permission_target["id"])
    target_url = f"{PANEL}/users/{target_id}"

    async def _put(url: str, **body: object):
        return await app_client.put(
            url, headers=app_auth_headers, json={"revision": revision, **body}
        )

    for key in catalog.KEYS:
        refused = await _put(
            target_url, action_changes=[{"action": key, "access": "none"}]
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"]["code"] == "additive_only"
        assert "tylko dodają" in refused.json()["detail"]["message"]

    level = await _put(
        target_url, action_changes=[{"action": "clients_edit", "access": "generate"}]
    )
    assert level.status_code == 422, level.text

    for section in ("delivery", "finance"):
        for access in ("none", "read", "write"):
            refused = await _put(
                target_url, changes=[{"section": section, "access": access}]
            )
            assert refused.status_code == 422, refused.text
            assert refused.json()["detail"] == {
                "code": "derived_section_access",
                "message": "Dostęp do Delivery i Finansów wynika z uprawnień.",
            }
    # Zdjęcie ograniczenia, którego nie ma, niczego nie zmienia — ale przechodzi.
    noop = await _put(
        target_url, changes=[{"section": "delivery", "access": "inherit"}]
    )
    assert noop.status_code == 200, noop.text
    assert noop.json() == {
        "revision": revision,
        "changed": False,
        "invalidated_users": 0,
    }

    viewer = await make_account(UserRole.user)
    viewer_url = f"{PANEL}/users/{viewer['id']}"
    refused = await _put(
        viewer_url, action_changes=[{"action": "delivery_view", "access": "manage"}]
    )
    assert refused.status_code == 422, refused.text
    assert refused.json()["detail"]["code"] == "role_not_grantable"
    viewer_detail = await app_client.get(viewer_url, headers=app_auth_headers)
    assert viewer_detail.json()["user"]["grantable"] is False

    missing = await app_client.get(
        f"{PANEL}/users/2147483600", headers=app_auth_headers
    )
    assert missing.status_code == 404
    missing_put = await _put(
        f"{PANEL}/users/2147483600",
        action_changes=[{"action": "delivery_view", "access": "manage"}],
    )
    assert missing_put.status_code == 404

    # Nic z powyższego nie zmieniło polityki.
    assert (await _snapshot(app_client, app_auth_headers))["revision"] == revision


async def test_legacy_restrictions_are_listed_and_can_only_be_lifted(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    """Stare wyjątki odbierające: ekran ich nie tworzy, ale pozwala zdjąć."""

    account = await make_account(UserRole.delivery_lead)
    target_id = int(account["id"])
    async with AsyncSessionLocal() as db:
        db.add(
            UserActionOverride(
                user_id=target_id, action="b2b_signature_confirmation", access="none"
            )
        )
        db.add(
            UserSectionOverride(user_id=target_id, section="delivery", access="read")
        )
        await db.commit()

    target_url = f"{PANEL}/users/{target_id}"
    before = (await app_client.get(target_url, headers=app_auth_headers)).json()
    person = before["user"]
    assert person["restrictions"] == ["b2b_signature_confirmation"]
    assert person["legacy_section_caps"] == {"delivery": "read"}
    assert "b2b_signature_confirmation" in person["role_permissions"]
    assert "b2b_signature_confirmation" not in person["effective"]
    # Stare ograniczenie sekcji tylko obniża: uprawnienia zostają, zapis nie.
    limited = await _login(app_client, account)
    me = await app_client.get("/api/auth/me", headers=limited)
    assert me.json()["effective_section_access"]["delivery"] == "read"

    lifted = await app_client.put(
        target_url,
        headers=app_auth_headers,
        json={
            "revision": before["revision"],
            "changes": [{"section": "delivery", "access": "inherit"}],
            "action_changes": [
                {"action": "b2b_signature_confirmation", "access": "inherit"}
            ],
        },
    )
    assert lifted.status_code == 200, lifted.text
    assert lifted.json()["changed"] is True

    after = (await app_client.get(target_url, headers=app_auth_headers)).json()["user"]
    assert after["restrictions"] == []
    assert after["legacy_section_caps"] == {}
    assert "b2b_signature_confirmation" in after["effective"]
    restored = await _login(app_client, account)
    me = await app_client.get("/api/auth/me", headers=restored)
    assert me.json()["effective_section_access"]["delivery"] == "write"

    async with AsyncSessionLocal() as db:
        event = await db.scalar(
            select(CriticalEvent)
            .where(
                CriticalEvent.event_type == "rbac.user_permissions",
                CriticalEvent.entity_id == target_id,
            )
            .order_by(CriticalEvent.id.desc())
        )
        assert event is not None
        assert event.reason == (
            "Usunięto ograniczenie: „Umowy B2B: oznaczanie jako podpisane”. "
            "Inne: section:delivery: read → inherit."
        )


# ── Rola: przełącznik, walidacja, zasiew ─────────────────────────────────────


async def test_switching_a_role_permission_off_closes_the_route_and_names_it(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    make_account: Callable[[UserRole], Awaitable[Account]],
) -> None:
    """To, co admin przełącza na ekranie, decyduje na trasie — w obie strony."""

    account = await make_account(UserRole.finance)
    original = await _role_action_rows("finance")
    assert original["finance_module"][0] == "manage"
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]
    last_event = await _last_event_id()

    headers = await _login(app_client, account)
    allowed = await app_client.get("/api/settings/event-history", headers=headers)
    assert allowed.status_code == 200, allowed.text

    try:
        switch = await app_client.put(
            f"{PANEL}/roles",
            headers=app_auth_headers,
            json={
                "revision": revision,
                "action_changes": [
                    {"role": "finance", "action": "finance_module", "access": "none"}
                ],
            },
        )
        assert switch.status_code == 200, switch.text
        assert switch.json()["revision"] == revision + 1
        assert switch.json()["changed"] is True
        assert switch.json()["invalidated_users"] >= 1

        # Zmiana uprawnień roli wylogowuje jej konta.
        stale = await app_client.get("/api/settings/event-history", headers=headers)
        assert stale.status_code == 401, stale.text
        headers = await _login(app_client, account)
        denied = await app_client.get("/api/settings/event-history", headers=headers)
        assert denied.status_code == 403, denied.text
        detail = denied.json()["detail"]
        assert detail["code"] == "permission_denied"
        assert detail["permission"] == "finance_module"
        assert "Moduł Finanse" in detail["message"]

        after = await _snapshot(app_client, app_auth_headers)
        finance = next(row for row in after["roles"] if row["role"] == "finance")
        assert finance["named"]["finance_module"] == {
            "granted": False,
            "effective": False,
            "implied_by": [],
        }
        assert finance["permissions"]["finance"] == "none"
        # Zmiana kwot została, więc podgląd kwot i zapis w Delivery też.
        assert finance["named"]["amounts_view"]["effective"] is True
        assert finance["permissions"]["delivery"] == "write"

        async with AsyncSessionLocal() as db:
            audit = await db.scalar(
                select(RbacPermissionAudit)
                .where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
                .order_by(RbacPermissionAudit.id.desc())
            )
            assert audit is not None
            assert audit.target_key == "finance"
            assert audit.before == {"finance:action:finance_module": "manage"}
            assert audit.after == {"finance:action:finance_module": "none"}
            event = await db.scalar(
                select(CriticalEvent)
                .where(
                    CriticalEvent.id > last_event,
                    CriticalEvent.event_type == "rbac.role_permissions",
                )
                .order_by(CriticalEvent.id.desc())
            )
            assert event is not None
            assert event.entity_type == "role"
            assert event.entity_id is None
            assert event.entity_label == "Finanse"
            assert event.outcome == "executed"
            assert event.reason == "Wyłączono: „Moduł Finanse”."
            assert event.details == {
                "role": "finance",
                "revision": revision + 1,
                "changes": {"finance_module": {"from": "manage", "to": "none"}},
            }

        back = await app_client.put(
            f"{PANEL}/roles",
            headers=app_auth_headers,
            json={
                "revision": revision + 1,
                "action_changes": [
                    {"role": "finance", "action": "finance_module", "access": "manage"}
                ],
            },
        )
        assert back.status_code == 200, back.text
        headers = await _login(app_client, account)
        again = await app_client.get("/api/settings/event-history", headers=headers)
        assert again.status_code == 200, again.text
    finally:
        await _restore_role_action_rows("finance", original)
        await _drop_role_traces(after_event_id=last_event, after_revision=revision)


async def test_role_changes_reject_levels_derived_sections_and_closed_roles(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]

    async def _put(**body: object):
        return await app_client.put(
            f"{PANEL}/roles",
            headers=app_auth_headers,
            json={"revision": revision, **body},
        )

    for section in ("delivery", "finance"):
        refused = await _put(
            changes=[{"role": "recruiter", "section": section, "access": "write"}]
        )
        assert refused.status_code == 422, refused.text
        assert refused.json()["detail"] == {
            "code": "derived_section_access",
            "message": "Dostęp do Delivery i Finansów wynika z uprawnień.",
        }

    for access in ("view", "generate"):
        level = await _put(
            action_changes=[
                {"role": "recruiter", "action": "clients_edit", "access": access}
            ]
        )
        assert level.status_code == 422, level.text
        assert catalog.label("clients_edit") in level.text

    for role in ("user", "trainee"):
        for access in ("manage", "none"):
            closed = await _put(
                action_changes=[
                    {"role": role, "action": "delivery_view", "access": access}
                ]
            )
            assert closed.status_code == 422, closed.text
            assert closed.json()["detail"]["code"] == "role_not_grantable"

    admin = await _put(
        action_changes=[{"role": "admin", "action": "clients_edit", "access": "none"}]
    )
    assert admin.status_code == 422, admin.text
    assert admin.json()["detail"]["code"] == "immutable_admin_access"

    unknown = await _put(
        action_changes=[
            {"role": "recruiter", "action": "everything", "access": "manage"}
        ]
    )
    assert unknown.status_code == 422, unknown.text

    assert (await _snapshot(app_client, app_auth_headers))["revision"] == revision


async def test_first_real_change_writes_the_whole_seed_of_an_unseeded_role(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
) -> None:
    """Rola bez wierszy zasiewu nie może zostać „zasiana częściowo”.

    Resolver liczy taką rolę funkcją zasiewu. Zapis jednego wiersza zamknąłby
    jej wszystko inne (brak wiersza = „nie”), więc pierwsza zmiana zapisuje
    komplet, a audyt mówi, co było efektywne.
    """

    role = "talent_community_manager"
    original = await _role_action_rows(role)
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]
    last_event = await _last_event_id()
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(RoleActionPermission).where(
                RoleActionPermission.role == role,
                RoleActionPermission.action.in_(catalog.SEEDED_KEYS),
            )
        )
        await db.commit()

    try:
        policy = await _snapshot(app_client, app_auth_headers)
        assert policy["revision"] == revision
        shown = next(row for row in policy["roles"] if row["role"] == role)
        # Bez wierszy ekran pokazuje to samo, co policzy resolver z sekcji roli.
        assert shown["named"]["delivery_view"]["granted"] is True
        assert shown["named"]["contract_status"]["granted"] is True
        assert shown["named"]["contracts_orders_edit"]["granted"] is False
        assert shown["permissions"]["delivery"] == "write"

        # Zapis tego, co rola już ma z zasiewu, niczego nie zmienia i nie pisze.
        same = await app_client.put(
            f"{PANEL}/roles",
            headers=app_auth_headers,
            json={
                "revision": revision,
                "action_changes": [
                    {"role": role, "action": "contract_status", "access": "manage"}
                ],
            },
        )
        assert same.status_code == 200, same.text
        assert same.json() == {
            "revision": revision,
            "changed": False,
            "invalidated_users": 0,
        }
        assert set(await _role_action_rows(role)).isdisjoint(catalog.SEEDED_KEYS)

        change = await app_client.put(
            f"{PANEL}/roles",
            headers=app_auth_headers,
            json={
                "revision": revision,
                "action_changes": [
                    {
                        "role": role,
                        "action": "contracts_orders_edit",
                        "access": "manage",
                    }
                ],
            },
        )
        assert change.status_code == 200, change.text
        assert change.json()["revision"] == revision + 1
        assert change.json()["changed"] is True

        stored = {
            action: access
            for action, (access, _updated_by) in (await _role_action_rows(role)).items()
            if action in catalog.SEEDED_KEYS
        }
        assert stored == {
            "delivery_view": "manage",
            "clients_edit": "none",
            "contracts_orders_edit": "manage",
            "contract_status": "manage",
            "recruitment_manage": "none",
            "amounts_view": "none",
            "amounts_edit": "none",
            "finance_module": "none",
        }
        after = await _snapshot(app_client, app_auth_headers)
        shown = next(row for row in after["roles"] if row["role"] == role)
        assert shown["named"]["contract_status"]["granted"] is True
        assert shown["named"]["contracts_orders_edit"]["granted"] is True

        async with AsyncSessionLocal() as db:
            audit = await db.scalar(
                select(RbacPermissionAudit)
                .where(
                    RbacPermissionAudit.target_kind == "role",
                    RbacPermissionAudit.revision == revision + 1,
                )
                .order_by(RbacPermissionAudit.id.desc())
            )
            assert audit is not None
            changed_key = f"{role}:action:contracts_orders_edit"
            assert audit.before[changed_key] == "none"
            assert audit.after[changed_key] == "manage"
            kept_key = f"{role}:action:contract_status"
            assert audit.before[kept_key] == "manage"
            assert audit.after[kept_key] == "manage"
            assert "missing" not in audit.before.values()
    finally:
        await _restore_role_action_rows(role, original)
        await _drop_role_traces(after_event_id=last_event, after_revision=revision)


async def test_technical_admin_access_cannot_be_delegated_or_overridden(
    app_client: AsyncClient,
    app_auth_headers: dict[str, str],
    permission_target: Account,
) -> None:
    revision = (await _snapshot(app_client, app_auth_headers))["revision"]

    role_change = await app_client.put(
        f"{PANEL}/roles",
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
        f"{PANEL}/users/{permission_target['id']}",
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
    # Sekcja ustawiana ręcznie — Delivery i Finanse wynikają z uprawnień.
    section = "insights"
    key = f"{role}:{section}"
    async with AsyncSessionLocal() as db:
        stored = await db.scalar(
            select(RoleSectionPermission).where(
                RoleSectionPermission.role == role,
                RoleSectionPermission.section == section,
            )
        )
        original_access = stored.access if stored is not None else "read"
        await db.execute(
            delete(RoleSectionPermission).where(
                RoleSectionPermission.role == role,
                RoleSectionPermission.section == section,
            )
        )
        await db.commit()
    last_event = await _last_event_id()

    policy = await _snapshot(app_client, app_auth_headers)
    revision = policy["revision"]
    role_row = next(row for row in policy["roles"] if row["role"] == role)
    assert role_row["permissions"][section] == "none"

    try:
        response = await app_client.put(
            f"{PANEL}/roles",
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
                        access=original_access,
                    )
                )
            else:
                restored.access = original_access
            await db.commit()
        await _drop_role_traces(after_event_id=last_event, after_revision=revision)


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
    last_event = await _last_event_id()

    policy = await _snapshot(app_client, app_auth_headers)
    revision = policy["revision"]
    role_row = next(row for row in policy["roles"] if row["role"] == role)
    assert role_row["action_permissions"][action] == "none"

    try:
        response = await app_client.put(
            f"{PANEL}/roles",
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
            await db.commit()
        await _drop_role_traces(after_event_id=last_event, after_revision=revision)


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
                        {"role": "user", "section": "insights", "access": "write"}
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
