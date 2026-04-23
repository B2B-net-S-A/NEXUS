"""API-level testy dla /api/marketplace/* (in-process ASGI)."""

from __future__ import annotations

import uuid
from datetime import date, timedelta

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import AvailabilityStatus, Candidate, CandidateStatus
from app.models.marketplace_alert_log import MarketplaceAlertLog
from app.models.talent_pool import TalentPool, TalentPoolMembership


pytestmark = pytest.mark.asyncio


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
            delete(TalentPoolMembership).where(
                TalentPoolMembership.candidate_id == cid
            )
        )
        await db.execute(
            delete(MarketplaceAlertLog).where(
                MarketplaceAlertLog.candidate_id == cid
            )
        )
        cand = await db.get(Candidate, cid)
        if cand is not None:
            await db.delete(cand)
        await db.commit()


async def test_get_pool_returns_singleton(
    app_client: AsyncClient, app_auth_headers: dict
):
    resp = await app_client.get(
        "/api/marketplace/pool", headers=app_auth_headers
    )
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
