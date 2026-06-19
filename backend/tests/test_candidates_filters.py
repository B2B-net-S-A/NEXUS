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


async def _seed_candidate(
    *,
    location: str | None,
    created_by: int | None,
    expected_rate_hourly: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Flt",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"flt-{uuid.uuid4().hex[:8]}@example.com",
            location=location,
            created_by=created_by,
            expected_rate_hourly=expected_rate_hourly,
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


async def _seed_candidate_with_status(
    *,
    status: str,
    availability: str | None = None,
) -> int:
    """Variant of _seed_candidate that lets us set status/availability."""
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import (
        AvailabilityStatus,
        Candidate,
        CandidateStatus,
    )

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Mst",
            lastname=f"Status-{uuid.uuid4().hex[:6]}",
            email=f"mst-{uuid.uuid4().hex[:8]}@example.com",
            location="Warszawa",
            status=CandidateStatus(status),
            availability_status=(
                AvailabilityStatus(availability) if availability else None
            ),
            created_by=None,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


@pytest.mark.asyncio
async def test_status_filter_accepts_multiple_values(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Repeating `?status=...` returns the OR-union of those statuses."""
    a = await _seed_candidate_with_status(status="active")
    p = await _seed_candidate_with_status(status="passive")
    b = await _seed_candidate_with_status(status="blacklisted")
    try:
        r = await app_client.get(
            "/api/candidates?status=active&status=passive&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert a in ids
        assert p in ids
        assert b not in ids
    finally:
        await _cleanup([a, p, b], None, [])


@pytest.mark.asyncio
async def test_status_filter_single_value_back_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Single `?status=active` (legacy URL) still works after multi conversion."""
    a = await _seed_candidate_with_status(status="active")
    p = await _seed_candidate_with_status(status="passive")
    try:
        r = await app_client.get(
            "/api/candidates?status=active&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert a in ids
        assert p not in ids
    finally:
        await _cleanup([a, p], None, [])


@pytest.mark.asyncio
async def test_status_filter_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/candidates?status=bogus",
        headers=app_auth_headers,
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_availability_filter_accepts_multiple_values(
    app_client: AsyncClient, app_auth_headers: dict
):
    al = await _seed_candidate_with_status(
        status="active", availability="actively_looking"
    )
    op = await _seed_candidate_with_status(
        status="active", availability="open_to_offers"
    )
    nl = await _seed_candidate_with_status(
        status="active", availability="not_looking"
    )
    try:
        r = await app_client.get(
            "/api/candidates?availability=actively_looking"
            "&availability=open_to_offers&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert al in ids
        assert op in ids
        assert nl not in ids
    finally:
        await _cleanup([al, op, nl], None, [])


@pytest.mark.asyncio
async def test_employment_filter_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/candidates?employment=bogus",
        headers=app_auth_headers,
    )
    assert r.status_code == 422


async def _seed_candidate_with_open_to(
    *,
    open_to_side_projects: bool = False,
    open_to_sales_support: bool = False,
    open_to_expert_consult: bool = False,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="OpenTo",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"openflt-{uuid.uuid4().hex[:8]}@example.com",
            open_to_side_projects=open_to_side_projects,
            open_to_sales_support=open_to_sales_support,
            open_to_expert_consult=open_to_expert_consult,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


@pytest.mark.asyncio
async def test_open_to_single_flag_filters_correctly(
    app_client: AsyncClient, app_auth_headers: dict
):
    side = await _seed_candidate_with_open_to(open_to_side_projects=True)
    sales = await _seed_candidate_with_open_to(open_to_sales_support=True)
    none = await _seed_candidate_with_open_to()
    try:
        r = await app_client.get(
            "/api/candidates?open_to=side_projects&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert side in ids
        assert sales not in ids
        assert none not in ids
    finally:
        await _cleanup([side, sales, none], None, [])


@pytest.mark.asyncio
async def test_open_to_multi_value_is_or_combined(
    app_client: AsyncClient, app_auth_headers: dict
):
    side = await _seed_candidate_with_open_to(open_to_side_projects=True)
    sales = await _seed_candidate_with_open_to(open_to_sales_support=True)
    expert = await _seed_candidate_with_open_to(open_to_expert_consult=True)
    none = await _seed_candidate_with_open_to()
    try:
        r = await app_client.get(
            "/api/candidates?open_to=side_projects&open_to=sales_support&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert side in ids
        assert sales in ids
        assert expert not in ids
        assert none not in ids
    finally:
        await _cleanup([side, sales, expert, none], None, [])


@pytest.mark.asyncio
async def test_open_to_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    r = await app_client.get(
        "/api/candidates?open_to=bogus",
        headers=app_auth_headers,
    )
    assert r.status_code == 422


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


@pytest.mark.asyncio
async def test_filter_by_expected_rate_hourly_range(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`min_rate`/`max_rate` band-filter on expected_rate_hourly, excluding nulls.

    Mirrors the `min_salary`/`max_salary` "exclusive of nulls" contract: a
    candidate with no expected rate never matches a bounded query.
    """
    low = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=100)
    inside = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=150)
    high = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=250)
    none = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=None)
    try:
        r = await app_client.get(
            "/api/candidates?min_rate=120&max_rate=200&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert inside in ids          # 150 ∈ [120, 200]
        assert low not in ids         # 100 < 120
        assert high not in ids        # 250 > 200
        assert none not in ids        # NULL excluded (exclusive of nulls)
    finally:
        await _cleanup([low, inside, high, none], None, [])


@pytest.mark.asyncio
async def test_filter_by_expected_rate_hourly_min_only(
    app_client: AsyncClient, app_auth_headers: dict
):
    low = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=90)
    high = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=200)
    none = await _seed_candidate(location="W", created_by=None, expected_rate_hourly=None)
    try:
        r = await app_client.get(
            "/api/candidates?min_rate=120&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert high in ids            # 200 >= 120
        assert low not in ids         # 90 < 120
        assert none not in ids        # NULL excluded
    finally:
        await _cleanup([low, high, none], None, [])


@pytest.mark.asyncio
async def test_filter_expected_rate_response_roundtrips(
    app_client: AsyncClient, app_auth_headers: dict
):
    """PATCH sets expected_rate_hourly/currency and the response echoes them."""
    cid = await _seed_candidate(location="W", created_by=None)
    try:
        patch = await app_client.patch(
            f"/api/candidates/{cid}",
            json={"expected_rate_hourly": 175, "expected_rate_currency": "PLN"},
            headers=app_auth_headers,
        )
        assert patch.status_code == 200, patch.text
        body = patch.json()
        assert body["expected_rate_hourly"] == 175
        assert body["expected_rate_currency"] == "PLN"
    finally:
        await _cleanup([cid], None, [])
