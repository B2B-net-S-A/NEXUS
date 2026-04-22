"""Tests dla /api/procedures — wewnętrzne SOP.

Pokrywa:
- RBAC: admin pełne CRUD, non-admin read-only (403 na modyfikacje)
- Search: ILIKE po title i content, case-insensitive
- published_only: non-admin zawsze widzi tylko opublikowane
- Slug: unikalny + sufiks przy kolizji
- Update: zmiana title → regeneracja slug
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.user import User, UserRole


# ── Helper: seed user + login (powielony wzorzec z test_rbac.py) ────────────


async def _seed_user(role: UserRole, label: str = "") -> tuple[str, str]:
    unique = uuid.uuid4().hex[:8]
    suffix = f"-{label}" if label else ""
    email = f"procedures{suffix}-{role.value}-{unique}@example.com"
    password = f"T3st_{unique}!Proc"

    async with AsyncSessionLocal() as db:
        existing = await db.scalar(select(User).where(User.email == email))
        if existing is None:
            u = User(
                email=email,
                password_hash=hash_password(password),
                name=f"Proc Test {role.value}",
                role=role,
                is_active=True,
            )
            db.add(u)
            await db.commit()
            await db.refresh(u)
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    resp = await client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, f"login failed: {resp.text}"
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest_asyncio.fixture
async def proc_client() -> AsyncClient:
    from app.main import app
    from app.core.rate_limit import limiter as _limiter

    _limiter.enabled = False
    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as c:
        yield c


@pytest_asyncio.fixture
async def admin_headers(proc_client: AsyncClient) -> dict[str, str]:
    email, password = await _seed_user(UserRole.admin, "admin")
    return await _login(proc_client, email, password)


@pytest_asyncio.fixture
async def recruiter_headers(proc_client: AsyncClient) -> dict[str, str]:
    email, password = await _seed_user(UserRole.recruiter, "rek")
    return await _login(proc_client, email, password)


# ── RBAC ────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_recruiter_cannot_create(proc_client, recruiter_headers):
    resp = await proc_client.post(
        "/api/procedures",
        headers=recruiter_headers,
        json={"title": "Should fail", "content": "hidden"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_cannot_update(proc_client, admin_headers, recruiter_headers):
    created = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": "Baza startowa", "content": "treść"},
    )
    assert created.status_code == 201
    pid = created.json()["id"]

    resp = await proc_client.put(
        f"/api/procedures/{pid}",
        headers=recruiter_headers,
        json={"title": "Inny tytuł"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_recruiter_cannot_delete(proc_client, admin_headers, recruiter_headers):
    created = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": "Do usunięcia", "content": "X"},
    )
    pid = created.json()["id"]

    resp = await proc_client.delete(
        f"/api/procedures/{pid}", headers=recruiter_headers
    )
    assert resp.status_code == 403


# ── Happy path ──────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_full_crud(proc_client, admin_headers):
    # Create
    create = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={
            "title": "Jak prowadzić rozmowę z kandydatem",
            "content": "# Krok 1\n- przywitaj się",
            "sort_order": 10,
        },
    )
    assert create.status_code == 201
    created = create.json()
    assert created["title"] == "Jak prowadzić rozmowę z kandydatem"
    assert created["slug"].startswith("jak-prowadzic")
    assert created["is_published"] is True
    pid = created["id"]

    # List
    listing = await proc_client.get("/api/procedures", headers=admin_headers)
    assert listing.status_code == 200
    slugs = [p["slug"] for p in listing.json()]
    assert created["slug"] in slugs

    # Get by id
    by_id = await proc_client.get(f"/api/procedures/{pid}", headers=admin_headers)
    assert by_id.status_code == 200
    assert by_id.json()["content"].startswith("# Krok")

    # Get by slug
    by_slug = await proc_client.get(
        f"/api/procedures/{created['slug']}", headers=admin_headers
    )
    assert by_slug.status_code == 200
    assert by_slug.json()["id"] == pid

    # Update
    upd = await proc_client.put(
        f"/api/procedures/{pid}",
        headers=admin_headers,
        json={"content": "Zaktualizowany", "sort_order": 99},
    )
    assert upd.status_code == 200
    assert upd.json()["content"] == "Zaktualizowany"
    assert upd.json()["sort_order"] == 99

    # Delete
    delete = await proc_client.delete(
        f"/api/procedures/{pid}", headers=admin_headers
    )
    assert delete.status_code == 204

    missing = await proc_client.get(
        f"/api/procedures/{pid}", headers=admin_headers
    )
    assert missing.status_code == 404


# ── Search ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_search_matches_title_and_content(proc_client, admin_headers):
    unique = uuid.uuid4().hex[:6]

    a = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": f"Onboarding klienta {unique}", "content": "proces zielonego światła"},
    )
    b = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": f"Procedura płatności {unique}", "content": f"magiczne-slowo-{unique} w środku"},
    )
    assert a.status_code == 201 and b.status_code == 201

    # match w title
    resp = await proc_client.get(
        "/api/procedures",
        headers=admin_headers,
        params={"q": f"Onboarding {unique}".lower()},
    )
    assert resp.status_code == 200
    titles = [p["title"] for p in resp.json()]
    assert any(f"Onboarding klienta {unique}" in t for t in titles)
    assert not any(f"Procedura płatności {unique}" in t for t in titles)

    # match w content
    resp2 = await proc_client.get(
        "/api/procedures",
        headers=admin_headers,
        params={"q": f"magiczne-slowo-{unique}"},
    )
    assert resp2.status_code == 200
    titles2 = [p["title"] for p in resp2.json()]
    assert any(f"Procedura płatności {unique}" in t for t in titles2)


# ── published_only ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_non_admin_sees_only_published(
    proc_client, admin_headers, recruiter_headers
):
    draft = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={
            "title": f"Szkic {uuid.uuid4().hex[:6]}",
            "content": "draft",
            "is_published": False,
        },
    )
    assert draft.status_code == 201
    slug = draft.json()["slug"]

    # Admin widzi szkic via published_only=false
    admin_list = await proc_client.get(
        "/api/procedures",
        headers=admin_headers,
        params={"published_only": "false"},
    )
    admin_slugs = [p["slug"] for p in admin_list.json()]
    assert slug in admin_slugs

    # Recruiter nie widzi szkicu (nawet z published_only=false)
    rek_list = await proc_client.get(
        "/api/procedures",
        headers=recruiter_headers,
        params={"published_only": "false"},
    )
    rek_slugs = [p["slug"] for p in rek_list.json()]
    assert slug not in rek_slugs

    # Recruiter dostaje 404 na szczegóły szkicu
    rek_detail = await proc_client.get(
        f"/api/procedures/{slug}", headers=recruiter_headers
    )
    assert rek_detail.status_code == 404


# ── Slug uniqueness ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_duplicate_title_yields_unique_slug(proc_client, admin_headers):
    title = f"Duplikat {uuid.uuid4().hex[:6]}"
    first = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": title, "content": "one"},
    )
    second = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": title, "content": "two"},
    )
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["slug"] != second.json()["slug"]
    assert second.json()["slug"].startswith(first.json()["slug"])


@pytest.mark.asyncio
async def test_update_title_regenerates_slug(proc_client, admin_headers):
    created = await proc_client.post(
        "/api/procedures",
        headers=admin_headers,
        json={"title": "Pierwotny tytuł", "content": "x"},
    )
    pid = created.json()["id"]
    old_slug = created.json()["slug"]

    upd = await proc_client.put(
        f"/api/procedures/{pid}",
        headers=admin_headers,
        json={"title": "Nowy inny tytuł"},
    )
    assert upd.status_code == 200
    new_slug = upd.json()["slug"]
    assert new_slug != old_slug
    assert "nowy" in new_slug


@pytest.mark.asyncio
async def test_unauthenticated_request_is_rejected(proc_client):
    resp = await proc_client.get("/api/procedures")
    # FastAPI HTTPBearer returns 403 when header missing
    assert resp.status_code in (401, 403)
