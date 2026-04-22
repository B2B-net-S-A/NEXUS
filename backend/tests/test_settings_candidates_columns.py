"""Tests for the candidates-columns settings endpoint with per-role scoping.

Covers:
  - GET returns hard-coded default when no row exists
  - PUT (admin, role=null) saves the global default; GET returns it
  - PUT (admin, role="recruiter") saves the role-specific default; only
    recruiters see it, admin falls back to the global default
  - GET /all returns every saved scope (admin-only)
  - Non-admin cannot PUT (403)
  - Invalid column id is rejected (422)
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select

from app.api.settings import DEFAULT_CANDIDATES_COLUMNS
from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.app_setting import AppSetting
from app.models.user import User, UserRole


@pytest_asyncio.fixture
async def recruiter_headers(app_client: AsyncClient) -> dict[str, str]:
    """Create a recruiter user on the fly and log in."""
    unique = uuid.uuid4().hex[:8]
    email = f"pytest-recruiter-{unique}@example.com"
    password = f"T3st_{unique}!PassX"

    async with AsyncSessionLocal() as db:
        db.add(
            User(
                email=email,
                password_hash=hash_password(password),
                name="Pytest Recruiter",
                role=UserRole.recruiter,
                is_active=True,
                profile_completed=True,
            )
        )
        await db.commit()

    resp = await app_client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture(autouse=True)
async def _cleanup_candidates_columns():
    """Isolate each test: drop every `candidates_columns*` row before and after."""
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AppSetting).where(AppSetting.key.like("candidates_columns%"))
        )
        for row in rows.all():
            await db.delete(row)
        await db.commit()
    yield
    async with AsyncSessionLocal() as db:
        rows = await db.scalars(
            select(AppSetting).where(AppSetting.key.like("candidates_columns%"))
        )
        for row in rows.all():
            await db.delete(row)
        await db.commit()


async def test_get_returns_hardcoded_default_when_empty(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/settings/candidates-columns", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == DEFAULT_CANDIDATES_COLUMNS


async def test_put_global_default_then_get_returns_it(
    app_client: AsyncClient, app_auth_headers: dict
):
    payload = {"columns": ["candidate", "position", "match"], "role": None}
    resp = await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json=payload,
    )
    assert resp.status_code == 200, resp.text

    resp = await app_client.get(
        "/api/settings/candidates-columns", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"columns": ["candidate", "position", "match"]}


async def test_put_role_specific_default_isolates_by_role(
    app_client: AsyncClient,
    app_auth_headers: dict,
    recruiter_headers: dict,
):
    # Global default: minimal set
    await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate"], "role": None},
    )
    # Recruiter-specific default: richer set
    resp = await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={
            "columns": ["candidate", "position", "match", "added_by"],
            "role": "recruiter",
        },
    )
    assert resp.status_code == 200, resp.text

    # Recruiter sees their role-specific default
    resp = await app_client.get(
        "/api/settings/candidates-columns", headers=recruiter_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "columns": ["candidate", "position", "match", "added_by"]
    }

    # Admin has no admin-specific default → falls back to global
    resp = await app_client.get(
        "/api/settings/candidates-columns", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert resp.json() == {"columns": ["candidate"]}


async def test_get_all_returns_every_scope(
    app_client: AsyncClient, app_auth_headers: dict
):
    await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate", "position"], "role": None},
    )
    await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate", "match"], "role": "recruiter"},
    )

    resp = await app_client.get(
        "/api/settings/candidates-columns/all", headers=app_auth_headers
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["global"] == {"columns": ["candidate", "position"]}
    assert body["recruiter"] == {"columns": ["candidate", "match"]}
    # Unset roles report None so the admin UI can render an empty state
    assert body["admin"] is None
    assert body["delivery_lead"] is None


async def test_get_all_is_admin_only(
    app_client: AsyncClient, recruiter_headers: dict
):
    resp = await app_client.get(
        "/api/settings/candidates-columns/all", headers=recruiter_headers
    )
    assert resp.status_code == 403


async def test_put_is_admin_only(
    app_client: AsyncClient, recruiter_headers: dict
):
    resp = await app_client.put(
        "/api/settings/candidates-columns",
        headers=recruiter_headers,
        json={"columns": ["candidate"], "role": None},
    )
    assert resp.status_code == 403


async def test_put_rejects_unknown_column(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate", "not_a_real_col"], "role": None},
    )
    assert resp.status_code == 422


async def test_put_rejects_missing_required_column(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["position", "match"], "role": None},
    )
    assert resp.status_code == 422


async def test_put_role_specific_is_scoped_separately_from_global(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Smoke check: changing role-specific default does NOT touch the global row."""
    await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate", "position"], "role": None},
    )
    await app_client.put(
        "/api/settings/candidates-columns",
        headers=app_auth_headers,
        json={"columns": ["candidate"], "role": "sourcer"},
    )

    async with AsyncSessionLocal() as db:
        global_row = await db.scalar(
            select(AppSetting).where(AppSetting.key == "candidates_columns")
        )
        sourcer_row = await db.scalar(
            select(AppSetting).where(
                AppSetting.key == "candidates_columns:sourcer"
            )
        )
        assert global_row is not None
        assert global_row.value == {"columns": ["candidate", "position"]}
        assert sourcer_row is not None
        assert sourcer_row.value == {"columns": ["candidate"]}
