"""Tests for /api/candidates `sort` query param.

Required for stable next/prev candidate navigation in the UI: two requests with
identical filters must return items in identical order. Without ORDER BY the
DB is free to return rows in plan-dependent order, breaking the navigation
sequence between page loads.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


async def _seed_candidate(
    *,
    name: str,
    lastname: str,
    created_at: datetime | None = None,
    created_by: int | None = None,
) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name=name,
            lastname=lastname,
            email=f"sort-{uuid.uuid4().hex[:10]}@example.com",
            created_by=created_by,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        if created_at is not None:
            from sqlalchemy import update

            await db.execute(
                update(Candidate)
                .where(Candidate.id == c.id)
                .values(created_at=created_at)
            )
            await db.commit()
        return c.id


async def _cleanup(candidate_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Candidate).where(Candidate.id.in_(candidate_ids)))
        await db.commit()


def _scoped_q(scope_id: str) -> str:
    """Lastname suffix shared by all candidates seeded for one test — used as
    a ?q=<scope_id> filter so we only assert on our seeded rows, not the
    whole DB which other tests may have polluted."""
    return scope_id


@pytest.mark.asyncio
async def test_sort_newest_orders_by_created_at_desc(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:10]
    base = datetime.now(timezone.utc) - timedelta(days=1)
    # Seed in reverse chronological order: c1 oldest, c3 newest.
    c1 = await _seed_candidate(name="Alice", lastname=scope, created_at=base)
    c2 = await _seed_candidate(
        name="Bob", lastname=scope, created_at=base + timedelta(minutes=1)
    )
    c3 = await _seed_candidate(
        name="Carol", lastname=scope, created_at=base + timedelta(minutes=2)
    )
    try:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": scope, "sort": "newest", "page": 1, "page_size": 50},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [c3, c2, c1], f"newest expected [c3, c2, c1], got {ids}"
    finally:
        await _cleanup([c1, c2, c3])


@pytest.mark.asyncio
async def test_sort_oldest_orders_by_created_at_asc(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:10]
    base = datetime.now(timezone.utc) - timedelta(days=1)
    c1 = await _seed_candidate(name="Alice", lastname=scope, created_at=base)
    c2 = await _seed_candidate(
        name="Bob", lastname=scope, created_at=base + timedelta(minutes=1)
    )
    c3 = await _seed_candidate(
        name="Carol", lastname=scope, created_at=base + timedelta(minutes=2)
    )
    try:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": scope, "sort": "oldest", "page": 1, "page_size": 50},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [c1, c2, c3], f"oldest expected [c1, c2, c3], got {ids}"
    finally:
        await _cleanup([c1, c2, c3])


@pytest.mark.asyncio
async def test_sort_name_orders_alphabetically(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:10]
    # Same created_at to prove sort is by name, not by created_at.
    base = datetime.now(timezone.utc)
    c_zoe = await _seed_candidate(name="Zoe", lastname=scope, created_at=base)
    c_amy = await _seed_candidate(name="Amy", lastname=scope, created_at=base)
    c_max = await _seed_candidate(name="Max", lastname=scope, created_at=base)
    try:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": scope, "sort": "name", "page": 1, "page_size": 50},
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [c_amy, c_max, c_zoe], (
            f"name expected [Amy, Max, Zoe], got ids={ids}"
        )
    finally:
        await _cleanup([c_zoe, c_amy, c_max])


@pytest.mark.asyncio
async def test_sort_default_is_newest(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    scope = uuid.uuid4().hex[:10]
    base = datetime.now(timezone.utc) - timedelta(days=1)
    c_old = await _seed_candidate(name="Old", lastname=scope, created_at=base)
    c_new = await _seed_candidate(
        name="New", lastname=scope, created_at=base + timedelta(hours=1)
    )
    try:
        resp = await app_client.get(
            "/api/candidates",
            params={"q": scope, "page": 1, "page_size": 50},  # no sort param
            headers=app_auth_headers,
        )
        assert resp.status_code == 200, resp.text
        ids = [item["id"] for item in resp.json()["items"]]
        assert ids == [c_new, c_old], f"default expected newest order, got {ids}"
    finally:
        await _cleanup([c_old, c_new])


@pytest.mark.asyncio
async def test_sort_is_stable_across_requests(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    """Two identical sorted requests must return identical id sequences. This
    is the property the next/prev candidate UI relies on."""
    scope = uuid.uuid4().hex[:10]
    # Use identical created_at on multiple candidates so the id tie-breaker
    # is exercised — without it Postgres can return rows in plan-order.
    same_ts = datetime.now(timezone.utc)
    seeded = [
        await _seed_candidate(name=f"Tie{i}", lastname=scope, created_at=same_ts)
        for i in range(8)
    ]
    try:
        params = {"q": scope, "sort": "newest", "page": 1, "page_size": 50}
        r1 = await app_client.get(
            "/api/candidates", params=params, headers=app_auth_headers
        )
        r2 = await app_client.get(
            "/api/candidates", params=params, headers=app_auth_headers
        )
        assert r1.status_code == 200 and r2.status_code == 200
        ids1 = [item["id"] for item in r1.json()["items"]]
        ids2 = [item["id"] for item in r2.json()["items"]]
        assert ids1 == ids2, (
            f"unstable order between requests:\n  first:  {ids1}\n  second: {ids2}"
        )
        # And the order must include all 8 we seeded.
        assert set(seeded).issubset(set(ids1))
    finally:
        await _cleanup(seeded)


@pytest.mark.asyncio
async def test_sort_rejects_invalid_value(
    app_client: AsyncClient, app_auth_headers: dict[str, str]
):
    resp = await app_client.get(
        "/api/candidates",
        params={"sort": "random"},
        headers=app_auth_headers,
    )
    assert resp.status_code == 422, resp.text
