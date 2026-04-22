"""Tests for new candidates list filters: added_by, talent_pool, location.

Uses in-process app fixtures (no live server needed).
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_user(*, name: str, role: str = "recruiter") -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"{uuid.uuid4().hex[:8]}-{name.lower().replace(' ', '')}@example.com",
            password_hash=hash_password("test-pass"),
            name=name,
            role=UserRole(role),
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_candidate(*, location: str | None, created_by: int | None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Flt",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"flt-{uuid.uuid4().hex[:8]}@example.com",
            location=location,
            created_by=created_by,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_pool_with(candidate_ids: list[int], name: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.talent_pool import TalentPool, TalentPoolMembership

    async with AsyncSessionLocal() as db:
        pool = TalentPool(name=f"{name}-{uuid.uuid4().hex[:6]}")
        db.add(pool)
        await db.commit()
        await db.refresh(pool)
        for cid in candidate_ids:
            db.add(TalentPoolMembership(talent_pool_id=pool.id, candidate_id=cid))
        await db.commit()
        return pool.id


async def _cleanup(candidate_ids: list[int], pool_id: int | None, user_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.talent_pool import TalentPool, TalentPoolMembership
    from app.models.user import User
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
        for uid in user_ids:
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()


@pytest.mark.asyncio
async def test_filter_by_added_by_single(
    app_client: AsyncClient, app_auth_headers: dict
):
    uid = await _seed_user(name="Rec A")
    mine = await _seed_candidate(location="Warszawa", created_by=uid)
    theirs = await _seed_candidate(location="Warszawa", created_by=None)
    try:
        r = await app_client.get(
            f"/api/candidates?added_by_user_id={uid}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert mine in ids
        assert theirs not in ids
    finally:
        await _cleanup([mine, theirs], None, [uid])


@pytest.mark.asyncio
async def test_filter_by_added_by_null_sentinel(
    app_client: AsyncClient, app_auth_headers: dict
):
    uid = await _seed_user(name="Rec B")
    mine = await _seed_candidate(location="Kraków", created_by=uid)
    system = await _seed_candidate(location="Kraków", created_by=None)
    try:
        r = await app_client.get(
            "/api/candidates?added_by_user_id=0&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = [item["id"] for item in r.json()["items"]]
        assert system in ids
        assert mine not in ids
    finally:
        await _cleanup([mine, system], None, [uid])


@pytest.mark.asyncio
async def test_filter_by_added_by_mixed_sentinel_and_users(
    app_client: AsyncClient, app_auth_headers: dict
):
    uid = await _seed_user(name="Rec C")
    mine = await _seed_candidate(location="Gdańsk", created_by=uid)
    system = await _seed_candidate(location="Gdańsk", created_by=None)
    other = await _seed_candidate(location="Gdańsk", created_by=None)
    try:
        r = await app_client.get(
            f"/api/candidates?added_by_user_id=0&added_by_user_id={uid}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = {item["id"] for item in r.json()["items"]}
        assert mine in ids
        assert system in ids
        assert other in ids  # also NULL, so matches the 0 sentinel
    finally:
        await _cleanup([mine, system, other], None, [uid])


@pytest.mark.asyncio
async def test_filter_by_talent_pool(
    app_client: AsyncClient, app_auth_headers: dict
):
    in_pool_1 = await _seed_candidate(location="Łódź", created_by=None)
    in_pool_2 = await _seed_candidate(location="Łódź", created_by=None)
    outside = await _seed_candidate(location="Łódź", created_by=None)
    pool_id = await _seed_pool_with([in_pool_1, in_pool_2], "QA pool")
    try:
        r = await app_client.get(
            f"/api/candidates?talent_pool_id={pool_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = {item["id"] for item in r.json()["items"]}
        assert in_pool_1 in ids
        assert in_pool_2 in ids
        assert outside not in ids
    finally:
        await _cleanup([in_pool_1, in_pool_2, outside], pool_id, [])


@pytest.mark.asyncio
async def test_filter_by_location_ilike(
    app_client: AsyncClient, app_auth_headers: dict
):
    a = await _seed_candidate(location="Warszawa, PL", created_by=None)
    b = await _seed_candidate(location="Remote — EU", created_by=None)
    try:
        r = await app_client.get(
            "/api/candidates?location=warszawa&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200
        ids = {item["id"] for item in r.json()["items"]}
        assert a in ids
        assert b not in ids
    finally:
        await _cleanup([a, b], None, [])


@pytest.mark.asyncio
async def test_create_candidate_sets_created_by(
    app_client: AsyncClient, app_auth_headers: dict
):
    payload = {
        "name": "Seed",
        "lastname": f"CreatedBy-{uuid.uuid4().hex[:6]}",
        "email": f"seed-{uuid.uuid4().hex[:8]}@example.com",
    }
    r = await app_client.post(
        "/api/candidates", json=payload, headers=app_auth_headers
    )
    assert r.status_code == 201, r.text
    data = r.json()
    assert isinstance(data.get("created_by"), int) and data["created_by"] > 0
    cid = data["id"]
    await _cleanup([cid], None, [])
