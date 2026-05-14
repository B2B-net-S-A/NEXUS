"""Tests for /api/user-email-templates — Phase 4.5 of the M365 plan.

Covers:
- CRUD happy path with auto-detected variables.
- 422 on invalid Jinja2 syntax.
- 403 when a non-owner tries to update/delete someone else's template.
- 200 when a non-owner LISTS / GETS a shared template.
- /render fills the context and returns unresolved vars when fields missing.
- Sandbox blocks dangerous attribute access (no Python introspection).

Uses the in-process `app_client` + `app_auth_headers` fixtures from conftest.py
— no live server required. The default admin is the owner unless we seed a
second user explicitly.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import Candidate
from app.models.user import User, UserRole
from app.models.user_email_template import UserEmailTemplate


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def cleanup_templates() -> AsyncIterator[None]:
    """Wipe any templates created by previous test runs in this DB."""
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserEmailTemplate))
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        await db.execute(delete(UserEmailTemplate))
        await db.commit()


@pytest_asyncio.fixture
async def seeded_candidate() -> AsyncIterator[int]:
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Jan",
            lastname="Kowalski",
            email=f"jan-{unique}@example.com",
            phone="+48 600 100 200",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        cid = c.id
    yield cid
    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


@pytest_asyncio.fixture
async def other_user() -> AsyncIterator[dict]:
    """A second user used to verify 403 on cross-user writes."""
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-other-{unique}@example.com"
    password = f"Pass_{unique}_X"

    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name="Pytest Other",
            role=UserRole.recruiter,
            is_active=True,
            profile_completed=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        uid = u.id

    yield {"id": uid, "email": email, "password": password}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(UserEmailTemplate).where(UserEmailTemplate.user_id == uid)
        )
        u = await db.scalar(select(User).where(User.id == uid))
        if u is not None:
            await db.delete(u)
        await db.commit()


async def _login(client: AsyncClient, email: str, password: str) -> dict:
    r = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ── CRUD happy path ─────────────────────────────────────────────────────────


async def test_create_and_list_template(
    app_client: AsyncClient, app_auth_headers: dict, cleanup_templates: None
):
    body = (
        "<p>Cześć {{ candidate.first_name }},</p>"
        "<p>Mam ciekawy temat — rola {{ request.role_name }}.</p>"
    )
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "Outreach intro",
            "subject": "Cześć {{ candidate.first_name }}",
            "body_html": body,
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["name"] == "Outreach intro"
    assert created["is_shared"] is False
    # Auto-detected vars — top-level only.
    assert set(created["variables"]) == {"candidate", "request"}

    r = await app_client.get("/api/user-email-templates", headers=app_auth_headers)
    assert r.status_code == 200
    items = r.json()
    assert any(t["id"] == created["id"] for t in items)


async def test_create_invalid_jinja_returns_422(
    app_client: AsyncClient, app_auth_headers: dict, cleanup_templates: None
):
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "Broken",
            "subject": None,
            "body_html": "<p>{{ unclosed </p>",
        },
        headers=app_auth_headers,
    )
    assert r.status_code == 422
    assert "Jinja2" in r.json()["detail"]


async def test_update_and_delete(
    app_client: AsyncClient, app_auth_headers: dict, cleanup_templates: None
):
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "v1",
            "subject": None,
            "body_html": "<p>hi {{ candidate.email }}</p>",
        },
        headers=app_auth_headers,
    )
    tid = r.json()["id"]

    r = await app_client.put(
        f"/api/user-email-templates/{tid}",
        json={"name": "v2", "body_html": "<p>{{ user.name }}</p>"},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    updated = r.json()
    assert updated["name"] == "v2"
    assert updated["variables"] == ["user"]

    r = await app_client.delete(
        f"/api/user-email-templates/{tid}", headers=app_auth_headers
    )
    assert r.status_code == 204

    r = await app_client.get(
        f"/api/user-email-templates/{tid}", headers=app_auth_headers
    )
    assert r.status_code == 404


# ── RBAC ────────────────────────────────────────────────────────────────────


async def test_other_user_cannot_modify(
    app_client: AsyncClient,
    app_auth_headers: dict,
    other_user: dict,
    cleanup_templates: None,
):
    # Admin (default) creates a private template.
    r = await app_client.post(
        "/api/user-email-templates",
        json={"name": "Admin private", "subject": None, "body_html": "<p>x</p>"},
        headers=app_auth_headers,
    )
    tid = r.json()["id"]

    # Other user logs in.
    other_headers = await _login(
        app_client, other_user["email"], other_user["password"]
    )

    # Cannot READ a private template owned by someone else.
    r = await app_client.get(f"/api/user-email-templates/{tid}", headers=other_headers)
    assert r.status_code == 404

    # Cannot UPDATE.
    r = await app_client.put(
        f"/api/user-email-templates/{tid}",
        json={"name": "hijack"},
        headers=other_headers,
    )
    assert r.status_code in (403, 404)

    # Cannot DELETE.
    r = await app_client.delete(
        f"/api/user-email-templates/{tid}", headers=other_headers
    )
    assert r.status_code in (403, 404)


async def test_shared_template_visible_to_others(
    app_client: AsyncClient,
    app_auth_headers: dict,
    other_user: dict,
    cleanup_templates: None,
):
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "Shared snippet",
            "subject": None,
            "body_html": "<p>{{ user.name }}</p>",
            "is_shared": True,
        },
        headers=app_auth_headers,
    )
    tid = r.json()["id"]

    other_headers = await _login(
        app_client, other_user["email"], other_user["password"]
    )

    r = await app_client.get(f"/api/user-email-templates/{tid}", headers=other_headers)
    assert r.status_code == 200
    assert r.json()["name"] == "Shared snippet"

    # But still cannot mutate it.
    r = await app_client.put(
        f"/api/user-email-templates/{tid}",
        json={"name": "hijack"},
        headers=other_headers,
    )
    assert r.status_code == 403


# ── Render ──────────────────────────────────────────────────────────────────


async def test_render_with_candidate(
    app_client: AsyncClient,
    app_auth_headers: dict,
    seeded_candidate: int,
    cleanup_templates: None,
):
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "Outreach",
            "subject": "Cześć {{ candidate.first_name }}",
            "body_html": (
                "<p>{{ candidate.full_name }} — rola: {{ request.role_name }}.</p>"
            ),
        },
        headers=app_auth_headers,
    )
    tid = r.json()["id"]

    r = await app_client.post(
        f"/api/user-email-templates/{tid}/render",
        json={"candidate_id": seeded_candidate},
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    out = r.json()
    assert "Jan" in out["rendered_subject"]
    assert "Jan Kowalski" in out["rendered_body_html"]
    # `request` has no row → unresolved attrs on it render as empty; the
    # top-level `request` key IS in context, so it's NOT unresolved.
    assert "request" not in out["unresolved_vars"]
    assert "candidate" not in out["unresolved_vars"]


async def test_render_unresolved_vars_listed(
    app_client: AsyncClient, app_auth_headers: dict, cleanup_templates: None
):
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "weird",
            "subject": None,
            "body_html": "<p>{{ candidate.first_name }} {{ totally_unknown }}</p>",
        },
        headers=app_auth_headers,
    )
    tid = r.json()["id"]

    r = await app_client.post(
        f"/api/user-email-templates/{tid}/render",
        json={},
        headers=app_auth_headers,
    )
    assert r.status_code == 200
    assert "totally_unknown" in r.json()["unresolved_vars"]


# ── Sandbox safety ──────────────────────────────────────────────────────────


async def test_sandbox_blocks_dangerous_attribute_access(
    app_client: AsyncClient, app_auth_headers: dict, cleanup_templates: None
):
    # Classic Jinja2 sandbox-escape attempt — SandboxedEnvironment should
    # raise SecurityError when the template tries to walk class internals.
    r = await app_client.post(
        "/api/user-email-templates",
        json={
            "name": "evil",
            "subject": None,
            "body_html": "{{ ().__class__.__bases__[0].__subclasses__() }}",
        },
        headers=app_auth_headers,
    )
    # The body parses as valid Jinja2 syntax → save succeeds.
    assert r.status_code == 201
    tid = r.json()["id"]

    r = await app_client.post(
        f"/api/user-email-templates/{tid}/render",
        json={},
        headers=app_auth_headers,
    )
    # SecurityError from the sandbox propagates as 422.
    assert r.status_code == 422
