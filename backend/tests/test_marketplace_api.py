"""API-level testy dla /api/marketplace/* (in-process ASGI)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.talent_pool import TalentPoolMembership
from app.models.user import User, UserRole


pytestmark = pytest.mark.asyncio


async def _seed_user_headers(
    app_client: AsyncClient, role: UserRole
) -> tuple[dict[str, str], int]:
    """Seed an active user with ``role``, log in, return (headers, user_id).

    Lets tests assert the write-endpoint role boundary directly instead of
    only through the admin ``app_auth_headers`` fixture.
    """
    suffix = uuid.uuid4().hex[:8]
    email = f"mp_{role.value}_{suffix}@example.com"
    password = f"T3st_{suffix}!PassX"
    async with AsyncSessionLocal() as db:
        u = User(
            email=email,
            password_hash=hash_password(password),
            name=f"MP {role.value}",
            role=role,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        uid = u.id
    resp = await app_client.post(
        "/api/auth/login", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, uid


async def _delete_user(user_id: int) -> None:
    async with AsyncSessionLocal() as db:
        u = await db.get(User, user_id)
        if u is not None:
            await db.delete(u)
            await db.commit()


@pytest_asyncio.fixture
async def seeded_candidate():
    """Tworzy kandydata bez poolowego wrzutu. Yield id, potem sprząta."""
    async with AsyncSessionLocal() as db:
        suffix = uuid.uuid4().hex[:8]
        cand = Candidate(
            name="APITest",
            lastname=f"Candidate_{suffix}",
            email=f"api_mp_{suffix}@example.com",
            status=CandidateStatus.active,
            availability_status=AvailabilityStatus.unknown,
        )
        db.add(cand)
        await db.commit()
        await db.refresh(cand)
        cid = cand.id
    yield cid
    async with AsyncSessionLocal() as db:
        # cleanup: memberships, alerts, candidate
        await db.execute(
            delete(TalentPoolMembership).where(TalentPoolMembership.candidate_id == cid)
        )
        await db.execute(
            delete(MarketplaceAlertLog).where(MarketplaceAlertLog.candidate_id == cid)
        )
        cand = await db.get(Candidate, cid)
        if cand is not None:
            await db.delete(cand)
        await db.commit()


async def test_get_pool_returns_singleton(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get("/api/marketplace/pool", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["is_marketplace"] is True
    assert "candidate_count" in data
    assert "id" in data


async def test_list_candidates_paginated(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/marketplace/candidates?page=1&page_size=10",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    assert "total" in data
    assert "page" in data
    assert data["page_size"] == 10


async def test_add_to_marketplace_defaults_30d(
    app_client: AsyncClient, app_auth_headers: dict, seeded_candidate: int
):
    resp = await app_client.post(
        f"/api/marketplace/candidates/{seeded_candidate}/add",
        json={},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["candidate_id"] == seeded_candidate
    assert data["source_event"] == "manual"

    expected = date.today() + timedelta(days=30)
    assert date.fromisoformat(data["marketplace_until"]) == expected


async def test_add_to_marketplace_custom_date(
    app_client: AsyncClient, app_auth_headers: dict, seeded_candidate: int
):
    target = (date.today() + timedelta(days=14)).isoformat()
    resp = await app_client.post(
        f"/api/marketplace/candidates/{seeded_candidate}/add",
        json={"marketplace_until": target},
        headers=app_auth_headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["marketplace_until"] == target


async def test_add_nonexistent_candidate_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.post(
        "/api/marketplace/candidates/999999/add",
        json={},
        headers=app_auth_headers,
    )
    assert resp.status_code == 404


async def test_remove_from_marketplace(
    app_client: AsyncClient, app_auth_headers: dict, seeded_candidate: int
):
    # Najpierw dodaj.
    await app_client.post(
        f"/api/marketplace/candidates/{seeded_candidate}/add",
        json={},
        headers=app_auth_headers,
    )
    # Usuń.
    resp = await app_client.delete(
        f"/api/marketplace/candidates/{seeded_candidate}",
        headers=app_auth_headers,
    )
    assert resp.status_code == 200, resp.text
    # Drugie usuwanie → 404.
    resp2 = await app_client.delete(
        f"/api/marketplace/candidates/{seeded_candidate}",
        headers=app_auth_headers,
    )
    assert resp2.status_code == 404


# ── Write-endpoint role boundary (RecruiterPlus) ─────────────────────────────
#
# „Wrzuć na targ" to akcja sourcingowa: rekruter / sourcer, który ma wolnego
# kandydata, MUSI móc go wystawić na targ. Wcześniej write był gated do TacPlus,
# więc rekruter/sourcer dostawał 403 mimo że UI pokazuje im przycisk.


@pytest.mark.parametrize("role", [UserRole.recruiter, UserRole.sourcer])
async def test_recruiter_and_sourcer_can_add_to_marketplace(
    app_client: AsyncClient, seeded_candidate: int, role: UserRole
):
    headers, uid = await _seed_user_headers(app_client, role)
    try:
        resp = await app_client.post(
            f"/api/marketplace/candidates/{seeded_candidate}/add",
            json={},
            headers=headers,
        )
        assert resp.status_code == 201, resp.text
        assert resp.json()["candidate_id"] == seeded_candidate
        # Symetria: kto może dodać, ten może też zdjąć.
        resp_del = await app_client.delete(
            f"/api/marketplace/candidates/{seeded_candidate}",
            headers=headers,
        )
        assert resp_del.status_code == 200, resp_del.text
    finally:
        await _delete_user(uid)


async def test_plain_user_cannot_add_to_marketplace(
    app_client: AsyncClient, seeded_candidate: int
):
    """Read-only viewer (`user` — QC / klient) zostaje poza RecruiterPlus → 403."""
    headers, uid = await _seed_user_headers(app_client, UserRole.user)
    try:
        resp = await app_client.post(
            f"/api/marketplace/candidates/{seeded_candidate}/add",
            json={},
            headers=headers,
        )
        assert resp.status_code == 403, resp.text
    finally:
        await _delete_user(uid)
