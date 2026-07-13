"""Tests for Phase 7.2 AAD group-based RBAC.

Three layers:

* Unit — :func:`map_groups_to_role` (pure function, no I/O).
* HTTP-mocked — :func:`fetch_user_groups` against a fake Graph response,
  asserting we filter ``#microsoft.graph.directoryRole`` rows out.
* Integration — the SSO callback end-to-end with ``AAD_GROUP_RBAC_ENABLED=True``,
  covering (a) successful role grant, (b) denial when no group matches, and
  (c) the admin ``/resync-aad-groups`` endpoint.

We avoid real HTTP by monkeypatching :class:`httpx.AsyncClient`.
"""

from __future__ import annotations

import json
import uuid
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.api import auth_microsoft as auth_ms_module
from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.rate_limit import limiter as _limiter
from app.core.security import create_access_token
from app.models.activity import Activity
from app.models.auth_exchange_code import AuthExchangeCode
from app.models.user import User, UserRole
from app.services.m365 import aad_groups as aad_groups_module
from app.services.m365.aad_groups import (
    fetch_user_groups,
    map_groups_to_role,
    map_groups_to_roles,
)


# ── Unit: map_groups_to_role ────────────────────────────────────────────────


def test_map_groups_to_role_first_match():
    mapping = {"g-admin": "admin", "g-rec": "recruiter"}
    assert map_groups_to_role(["g-rec"], mapping) == "recruiter"
    assert map_groups_to_role(["g-admin"], mapping) == "admin"


def test_map_groups_to_role_no_match_returns_none():
    mapping = {"g-admin": "admin"}
    assert map_groups_to_role(["g-other"], mapping) is None
    assert map_groups_to_role([], mapping) is None
    assert map_groups_to_role(["g-admin"], {}) is None


def test_map_groups_to_role_mapping_order_priority():
    """When user is in BOTH groups, the first key in the mapping wins."""
    mapping = {"g-admin": "admin", "g-rec": "recruiter"}
    # User is in both — should get admin (listed first).
    assert map_groups_to_role(["g-rec", "g-admin"], mapping) == "admin"
    # Reverse the mapping → recruiter now wins.
    mapping_reversed = {"g-rec": "recruiter", "g-admin": "admin"}
    assert map_groups_to_role(["g-rec", "g-admin"], mapping_reversed) == "recruiter"


# ── Unit: map_groups_to_roles (multi-role, migracja 0110) ──────────────────


def test_map_groups_to_roles_returns_all_matches_in_mapping_order():
    """Hybrid DL+TAC user gets both roles, ordered by mapping insertion."""
    mapping = {
        "g-admin": "admin",
        "g-dl": "delivery_lead",
        "g-tac": "tac",
        "g-rec": "recruiter",
    }
    # User in DL + TAC groups → both roles, DL first (precedes TAC in mapping).
    assert map_groups_to_roles(["g-tac", "g-dl"], mapping) == [
        "delivery_lead",
        "tac",
    ]
    # Reverse mapping order swaps the primary.
    mapping_rev = {
        "g-tac": "tac",
        "g-dl": "delivery_lead",
    }
    assert map_groups_to_roles(["g-tac", "g-dl"], mapping_rev) == ["tac", "delivery_lead"]


def test_map_groups_to_roles_empty_when_no_match():
    assert map_groups_to_roles(["g-other"], {"g-admin": "admin"}) == []
    assert map_groups_to_roles([], {"g-admin": "admin"}) == []
    assert map_groups_to_roles(["g-admin"], {}) == []


def test_map_groups_to_roles_dedupes_duplicate_role_values():
    """Two groups mapping to the same role should not produce duplicates."""
    mapping = {"g-rec-1": "recruiter", "g-rec-2": "recruiter"}
    assert map_groups_to_roles(["g-rec-1", "g-rec-2"], mapping) == ["recruiter"]


def test_map_groups_to_role_matches_map_groups_to_roles_first_element():
    """``map_groups_to_role`` (legacy) returns the same as ``roles[0]``."""
    mapping = {"g-admin": "admin", "g-tac": "tac"}
    groups = ["g-tac", "g-admin"]
    roles = map_groups_to_roles(groups, mapping)
    single = map_groups_to_role(groups, mapping)
    assert roles[0] == single


# ── HTTP-mocked: fetch_user_groups filters directory roles ──────────────────


class _FakeAsyncClient:
    """Mimic the slice of httpx.AsyncClient we use in aad_groups.fetch_user_groups."""

    def __init__(self, response_payload: dict, *, status_code: int = 200, **_kwargs):
        self._payload = response_payload
        self._status_code = status_code

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def get(self, url: str, headers: dict):  # noqa: ARG002
        # Return a fake httpx.Response. We use httpx.Response so the
        # production code's .raise_for_status() / .json() calls hit real
        # paths rather than relying on yet another mock.
        request = httpx.Request("GET", url)
        return httpx.Response(
            status_code=self._status_code,
            json=self._payload,
            request=request,
        )


@pytest.mark.asyncio
async def test_fetch_user_groups_filters_non_groups(monkeypatch):
    """Directory roles share /me/memberOf with groups — must be filtered out."""
    payload = {
        "value": [
            {
                "@odata.type": "#microsoft.graph.group",
                "id": "g-1",
                "displayName": "NEXUS-Recruiters",
            },
            {
                "@odata.type": "#microsoft.graph.directoryRole",
                "id": "role-1",
                "displayName": "Global Administrator",
            },
            {
                "@odata.type": "#microsoft.graph.group",
                "id": "g-2",
                "displayName": "NEXUS-Admins",
            },
            # Row missing id — must be skipped without raising.
            {
                "@odata.type": "#microsoft.graph.group",
                "displayName": "broken",
            },
        ]
    }

    def _factory(*args, **kwargs):
        return _FakeAsyncClient(payload)

    monkeypatch.setattr(aad_groups_module.httpx, "AsyncClient", _factory)

    groups = await fetch_user_groups("fake-access-token")
    assert len(groups) == 2
    assert {g["id"] for g in groups} == {"g-1", "g-2"}
    assert all("displayName" in g for g in groups)


@pytest.mark.asyncio
async def test_fetch_user_groups_raises_on_graph_error(monkeypatch):
    payload = {"error": {"code": "Forbidden"}}

    def _factory(*args, **kwargs):
        return _FakeAsyncClient(payload, status_code=403)

    monkeypatch.setattr(aad_groups_module.httpx, "AsyncClient", _factory)

    with pytest.raises(httpx.HTTPStatusError):
        await fetch_user_groups("bad-token")


# ── Integration: SSO callback end-to-end with RBAC enabled ──────────────────


@pytest.fixture(autouse=True)
def _disable_rate_limits():
    _limiter.enabled = False
    yield
    _limiter.enabled = True


@pytest.fixture(autouse=True)
def _force_sso_config(monkeypatch):
    monkeypatch.setattr(settings, "M365_INTEGRATION_ENABLED", True)
    # SSO login is now behind its own runtime kill-switch (default off). These
    # tests exercise the SSO callback end-to-end, so turn it on explicitly.
    monkeypatch.setattr(settings, "MICROSOFT_SSO_LOGIN_ENABLED", True)
    monkeypatch.setattr(settings, "M365_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "M365_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "M365_TENANT_ID", "test-tenant-id")
    monkeypatch.setattr(
        settings,
        "MICROSOFT_LOGIN_REDIRECT_URI",
        "https://api.test.example/api/auth/microsoft/callback",
    )
    monkeypatch.setattr(settings, "SSO_ALLOWED_DOMAINS", "b2bnetwork.pl")
    monkeypatch.setattr(settings, "PUBLIC_BASE_URL", "https://app.test.example")
    monkeypatch.setattr(
        settings,
        "M365_STATE_SIGNING_KEY",
        "test-state-key-at-least-48-chars-1234567890abcdefXYZ",
    )


@pytest_asyncio.fixture
async def app_client_no_redirect() -> AsyncIterator[AsyncClient]:
    from app.main import app

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://testserver",
        follow_redirects=False,
    ) as c:
        yield c


@pytest_asyncio.fixture
async def cleanup_users():
    emails: list[str] = []
    yield emails
    if not emails:
        return
    async with AsyncSessionLocal() as db:
        users = (await db.execute(select(User.id).where(User.email.in_(emails)))).all()
        if users:
            ids = [r[0] for r in users]
            await db.execute(
                delete(AuthExchangeCode).where(AuthExchangeCode.user_id.in_(ids))
            )
            await db.execute(delete(Activity).where(Activity.user_id.in_(ids)))
        await db.execute(delete(User).where(User.email.in_(emails)))
        await db.commit()


def _patch_token_exchange_with_access(
    monkeypatch, claims: dict, *, access_token: str = "fake-access-token"
):
    async def _fake(_code, _verifier):
        return {"claims": claims, "access_token": access_token}

    monkeypatch.setattr(auth_ms_module, "_exchange_code_for_id_token", _fake)


def _patch_fetch_groups(monkeypatch, groups: list[dict]):
    async def _fake(_access_token: str) -> list[dict]:
        return groups

    # Patch at the import site inside auth_microsoft.callback — it does a
    # `from app.services.m365.aad_groups import fetch_user_groups` so we have
    # to patch the source module.
    monkeypatch.setattr(aad_groups_module, "fetch_user_groups", _fake)


@pytest.mark.asyncio
async def test_sso_callback_grants_role_from_aad_group(
    app_client_no_redirect, monkeypatch, cleanup_users
):
    """Login with an AAD group that maps to ``admin`` → role becomes admin."""
    unique = uuid.uuid4().hex[:8]
    email = f"aad-admin-{unique}@b2bnetwork.pl"
    cleanup_users.append(email)

    admin_group = f"grp-admin-{unique}"
    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    monkeypatch.setattr(
        settings,
        "AAD_GROUP_ROLE_MAP_JSON",
        json.dumps({admin_group: "admin", f"grp-rec-{unique}": "recruiter"}),
    )

    _patch_token_exchange_with_access(
        monkeypatch,
        {
            "preferred_username": email,
            "oid": f"oid-{unique}",
            "name": "AAD Admin",
        },
    )
    _patch_fetch_groups(
        monkeypatch,
        [{"id": admin_group, "displayName": "NEXUS-Admins"}],
    )

    state = auth_ms_module._sign_login_state("v" * 64)
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "graph-code", "state": state},
    )
    assert resp.status_code == 302, resp.text
    # Success redirects to /login/microsoft/callback?code=...
    assert "/login/microsoft/callback" in resp.headers["location"]

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        assert u.role == UserRole.admin
        assert u.is_active is True
        # aad_group_ids snapshotted exactly as Graph returned.
        assert isinstance(u.aad_group_ids, list)
        assert any(g.get("id") == admin_group for g in u.aad_group_ids)


@pytest.mark.asyncio
async def test_sso_callback_blocks_user_with_no_matching_group(
    app_client_no_redirect, monkeypatch, cleanup_users
):
    """No AAD group matches → 302 to /login with error, is_active=False, no JWT."""
    unique = uuid.uuid4().hex[:8]
    email = f"aad-noaccess-{unique}@b2bnetwork.pl"
    cleanup_users.append(email)

    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    # Mapping has no entry matching the user's groups.
    monkeypatch.setattr(
        settings,
        "AAD_GROUP_ROLE_MAP_JSON",
        json.dumps({"grp-admin-only": "admin"}),
    )

    _patch_token_exchange_with_access(
        monkeypatch,
        {
            "preferred_username": email,
            "oid": f"oid-{unique}",
            "name": "No Access",
        },
    )
    _patch_fetch_groups(
        monkeypatch,
        [{"id": "grp-marketing", "displayName": "NEXUS-Marketing"}],
    )

    state = auth_ms_module._sign_login_state("v" * 64)
    resp = await app_client_no_redirect.get(
        "/api/auth/microsoft/callback",
        params={"code": "graph-code", "state": state},
    )
    assert resp.status_code == 302
    # Error redirect to /login, NOT to /login/microsoft/callback.
    location = resp.headers["location"]
    assert "/login?" in location
    # Polish error message — keep stable for frontend i18n. URL-encoded form
    # has ``+`` for spaces, so match the URL-safe substring.
    assert "Microsoft+AD" in location or "Microsoft%20AD" in location

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.email == email))
        assert u is not None
        # User was created (we still need the row to track the denial) but
        # is_active is False so subsequent logins also fail.
        assert u.is_active is False
        # Audit row written.
        denial = await db.scalar(
            select(Activity)
            .where(Activity.entity_id == u.id)
            .where(Activity.action == "sso_aad_role_denied")
        )
        assert denial is not None


# ── Admin endpoint: /resync-aad-groups ──────────────────────────────────────


@pytest_asyncio.fixture
async def admin_token() -> tuple[int, str]:
    """Create a one-shot admin user + signed JWT for the resync tests."""
    email = f"resync-admin-{uuid.uuid4().hex[:8]}@b2bnetwork.pl"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=None,
            name="Resync Admin",
            role=UserRole.admin,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        admin_id = u.id

    token = create_access_token(admin_id, UserRole.admin.value)
    yield admin_id, token

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Activity).where(Activity.user_id == admin_id))
        await db.execute(delete(User).where(User.id == admin_id))
        await db.commit()


@pytest.mark.asyncio
async def test_resync_endpoint_422_when_rbac_disabled(
    app_client_no_redirect, monkeypatch, admin_token
):
    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", False)
    _admin_id, token = admin_token

    resp = await app_client_no_redirect.post(
        "/api/admin/users/1/resync-aad-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert "AAD_GROUP_RBAC_ENABLED=false" in resp.text


@pytest.mark.asyncio
async def test_resync_endpoint_remaps_role_from_stored_groups(
    app_client_no_redirect, monkeypatch, admin_token, cleanup_users
):
    """Admin changes AAD_GROUP_ROLE_MAP_JSON → resync flips user's role."""
    unique = uuid.uuid4().hex[:8]
    email = f"resync-target-{unique}@b2bnetwork.pl"
    cleanup_users.append(email)

    rec_group = f"grp-rec-{unique}"
    # Seed: user with one stored AAD group, currently role=recruiter.
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=None,
            name="Resync Target",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
            aad_group_ids=[{"id": rec_group, "displayName": "NEXUS-Recruiters"}],
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        target_id = u.id

    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    # Mapping now says THIS group grants admin (admin remapped existing group).
    monkeypatch.setattr(
        settings,
        "AAD_GROUP_ROLE_MAP_JSON",
        json.dumps({rec_group: "admin"}),
    )

    _admin_id, token = admin_token
    resp = await app_client_no_redirect.post(
        f"/api/admin/users/{target_id}/resync-aad-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["previous_role"] == "recruiter"
    assert body["new_role"] == "admin"
    assert body["role_changed"] is True
    assert body["is_active"] is True

    async with AsyncSessionLocal() as db:
        u = await db.scalar(select(User).where(User.id == target_id))
        assert u.role == UserRole.admin


@pytest.mark.asyncio
async def test_resync_endpoint_422_when_user_has_no_stored_groups(
    app_client_no_redirect, monkeypatch, admin_token, cleanup_users
):
    """Legacy user (no aad_group_ids yet) → 422 with hint to login via SSO."""
    unique = uuid.uuid4().hex[:8]
    email = f"resync-empty-{unique}@b2bnetwork.pl"
    cleanup_users.append(email)

    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=None,
            name="Empty Groups",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
            aad_group_ids=[],
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        target_id = u.id

    monkeypatch.setattr(settings, "AAD_GROUP_RBAC_ENABLED", True)
    monkeypatch.setattr(settings, "AAD_GROUP_ROLE_MAP_JSON", json.dumps({"g": "admin"}))

    _admin_id, token = admin_token
    resp = await app_client_no_redirect.post(
        f"/api/admin/users/{target_id}/resync-aad-groups",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 422
    assert "log in via" in resp.text or "log in" in resp.text


# ── Config validator ────────────────────────────────────────────────────────


def test_aad_group_role_map_rejects_unknown_role(monkeypatch):
    monkeypatch.setattr(
        settings,
        "AAD_GROUP_ROLE_MAP_JSON",
        json.dumps({"g": "supreme_overlord"}),
    )
    with pytest.raises(ValueError, match="unknown role"):
        _ = settings.aad_group_role_map


def test_aad_group_role_map_rejects_malformed_json(monkeypatch):
    monkeypatch.setattr(settings, "AAD_GROUP_ROLE_MAP_JSON", "not-json{")
    with pytest.raises(ValueError, match="not valid JSON"):
        _ = settings.aad_group_role_map


def test_aad_group_role_map_empty_returns_empty_dict(monkeypatch):
    monkeypatch.setattr(settings, "AAD_GROUP_ROLE_MAP_JSON", "")
    assert settings.aad_group_role_map == {}
