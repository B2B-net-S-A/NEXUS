"""API tests for /api/cortex/* (RBAC, shapes, single-flight backfill guard)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.cortex import CortexExtractionRun
from app.models.user import User, UserRole


@pytest.mark.asyncio
async def test_tech_map_shape(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get("/api/cortex/tech-map", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    for key in (
        "cells",
        "skills",
        "skill_totals",
        "seniorities",
        "candidates_covered",
        "candidates_total",
        "fill_rate_pct",
        "sources",
        "data_as_of",
    ):
        assert key in data
    assert data["seniorities"] == ["junior", "mid", "senior", "unknown"]


@pytest.mark.asyncio
async def test_coverage_shape(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get("/api/cortex/coverage", headers=app_auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "candidates" in data and "facts" in data and "processes" in data
    assert "data_as_of" in data
    assert "with_any_fact_pct" in data["candidates"]
    assert set(data["facts"]["freshness"]) == {"lt_1y", "y1_3", "gt_3y", "unknown"}


@pytest.mark.asyncio
async def test_tech_map_rejects_recruiter(app_client: AsyncClient):
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
            )
        )
        await db.commit()

    try:
        login = await app_client.post(
            "/api/auth/login", json={"email": email, "password": password}
        )
        assert login.status_code == 200
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        resp = await app_client.get("/api/cortex/tech-map", headers=headers)
        assert resp.status_code == 403
        resp = await app_client.post(
            "/api/cortex/admin/backfill-traffit", headers=headers
        )
        assert resp.status_code == 403
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(delete(User).where(User.email == email))
            await db.commit()


@pytest.mark.asyncio
async def test_backfill_double_start_guard(app_client: AsyncClient, app_auth_headers):
    # Single-flight jest teraz trwały (partial unique `status='running'` na
    # cortex_extraction_runs): wstaw aktywny run i sprawdź że POST → 409.
    # started_at=now() (server_default) → orphan reaper go nie sprzątnie.
    async with AsyncSessionLocal() as db:
        run = CortexExtractionRun(
            run_type="manual", source="traffit", status="running"
        )
        db.add(run)
        await db.commit()
        run_id = run.id
    try:
        resp = await app_client.post(
            "/api/cortex/admin/backfill-traffit", headers=app_auth_headers
        )
        assert resp.status_code == 409
    finally:
        async with AsyncSessionLocal() as db:
            await db.execute(
                delete(CortexExtractionRun).where(CortexExtractionRun.id == run_id)
            )
            await db.commit()


@pytest.mark.asyncio
async def test_unmatched_terms_admin_only(app_client: AsyncClient, app_auth_headers):
    resp = await app_client.get(
        "/api/cortex/unmatched-terms", headers=app_auth_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)
