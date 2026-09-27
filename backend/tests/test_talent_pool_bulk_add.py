"""Tests for POST /api/talent-pools/{id}/bulk-add (Phase „Otwartość" Faza 2.5)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Bulk",
            lastname=f"Pool-{uuid.uuid4().hex[:6]}",
            email=f"bulk-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_pool() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.talent_pool import TalentPool

    async with AsyncSessionLocal() as db:
        p = TalentPool(name=f"BulkPool-{uuid.uuid4().hex[:6]}")
        db.add(p)
        await db.commit()
        await db.refresh(p)
        return p.id


async def _cleanup(candidate_ids: list[int], pool_id: int | None) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.talent_pool import TalentPool, TalentPoolMembership
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        if pool_id is not None:
            await db.execute(
                delete(TalentPoolMembership).where(
                    TalentPoolMembership.talent_pool_id == pool_id
                )
            )
            await db.execute(delete(TalentPool).where(TalentPool.id == pool_id))
        for cid in candidate_ids:
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        await db.commit()


@pytest.mark.asyncio
async def test_bulk_add_happy_path(app_client: AsyncClient, app_auth_headers: dict):
    pool_id = await _seed_pool()
    a, b = await _seed_candidate(), await _seed_candidate()
    try:
        res = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": [a, b]},
            headers=app_auth_headers,
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["pool_id"] == pool_id
        assert body["requested"] == 2
        assert body["added"] == 2
        assert body["already_in_pool"] == 0
        assert body["not_found"] == 0
    finally:
        await _cleanup([a, b], pool_id)


@pytest.mark.asyncio
async def test_bulk_add_idempotent_skips_existing(
    app_client: AsyncClient, app_auth_headers: dict
):
    pool_id = await _seed_pool()
    a, b = await _seed_candidate(), await _seed_candidate()
    try:
        # First batch — both added
        await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": [a]},
            headers=app_auth_headers,
        )
        # Second batch — `a` already in, `b` new
        res = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": [a, b]},
            headers=app_auth_headers,
        )
        body = res.json()
        assert body["added"] == 1
        assert body["already_in_pool"] == 1
        assert body["not_found"] == 0
    finally:
        await _cleanup([a, b], pool_id)


@pytest.mark.asyncio
async def test_bulk_add_counts_not_found(
    app_client: AsyncClient, app_auth_headers: dict
):
    pool_id = await _seed_pool()
    a = await _seed_candidate()
    try:
        res = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": [a, 999_999_999]},
            headers=app_auth_headers,
        )
        body = res.json()
        assert body["added"] == 1
        assert body["not_found"] == 1
    finally:
        await _cleanup([a], pool_id)


@pytest.mark.asyncio
async def test_bulk_add_empty_list_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    pool_id = await _seed_pool()
    try:
        res = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": []},
            headers=app_auth_headers,
        )
        assert res.status_code == 422
    finally:
        await _cleanup([], pool_id)


@pytest.mark.asyncio
async def test_bulk_add_unknown_pool_returns_404(
    app_client: AsyncClient, app_auth_headers: dict
):
    res = await app_client.post(
        "/api/talent-pools/999999999/bulk-add",
        json={"candidate_ids": [1]},
        headers=app_auth_headers,
    )
    assert res.status_code == 404


async def _marketplace_pool_id() -> int:
    from app.core.database import AsyncSessionLocal
    from app.services.marketplace_service import ensure_marketplace_pool

    async with AsyncSessionLocal() as db:
        pool = await ensure_marketplace_pool(db)
        await db.commit()
        return pool.id


@pytest.mark.asyncio
async def test_generic_pool_routes_refuse_the_marketplace_pool(
    app_client: AsyncClient, app_auth_headers: dict
):
    """R10-N7-4: Targ ma własne trasy z terminem. Wpis z ogólnego /add albo
    /bulk-add nie miałby `marketplace_until` i nigdy by nie wygasł."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.talent_pool import TalentPoolMembership

    pool_id = await _marketplace_pool_id()
    a = await _seed_candidate()
    try:
        bulk = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": [a]},
            headers=app_auth_headers,
        )
        assert bulk.status_code == 409, bulk.text
        single = await app_client.post(
            f"/api/talent-pools/{pool_id}/add",
            json={"candidate_id": a},
            headers=app_auth_headers,
        )
        assert single.status_code == 409, single.text
        dropped = await app_client.delete(
            f"/api/talent-pools/{pool_id}/remove/{a}", headers=app_auth_headers
        )
        assert dropped.status_code == 409, dropped.text
        async with AsyncSessionLocal() as db:
            row = await db.scalar(
                select(TalentPoolMembership.id).where(
                    TalentPoolMembership.talent_pool_id == pool_id,
                    TalentPoolMembership.candidate_id == a,
                )
            )
        assert row is None

        listed = await app_client.get("/api/talent-pools", headers=app_auth_headers)
        assert listed.status_code == 200, listed.text
        flags = {p["id"]: p["is_marketplace"] for p in listed.json()}
        assert flags[pool_id] is True
    finally:
        await _cleanup([a], None)


@pytest.mark.asyncio
async def test_bulk_add_caps_the_id_list(
    app_client: AsyncClient, app_auth_headers: dict
):
    """R10-N7-11: ponad 1000 id = 422, nie 500 z asyncpg."""
    pool_id = await _seed_pool()
    try:
        res = await app_client.post(
            f"/api/talent-pools/{pool_id}/bulk-add",
            json={"candidate_ids": list(range(1, 40_001))},
            headers=app_auth_headers,
        )
        assert res.status_code == 422, res.text
    finally:
        await _cleanup([], pool_id)
