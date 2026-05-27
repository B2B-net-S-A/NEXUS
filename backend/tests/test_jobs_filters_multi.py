"""Multi-value filter tests for /api/jobs.

Verifies that `status` and `owner_id` accept repeated query params and that
single-value calls remain backward-compatible.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_user(*, role: str = "recruiter") -> int:
    from app.core.database import AsyncSessionLocal
    from app.core.security import hash_password
    from app.models.user import User, UserRole

    async with AsyncSessionLocal() as db:
        u = User(
            email=f"job-flt-{uuid.uuid4().hex[:8]}@example.com",
            password_hash=hash_password("test-pass"),
            name=f"JobFlt-{uuid.uuid4().hex[:6]}",
            role=UserRole(role),
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


async def _seed_client() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=f"JobFltClient-{uuid.uuid4().hex[:6]}")
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(*, status: str, recruiter_id: int | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    client_id = await _seed_client()
    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus(status),
            recruiter_id=recruiter_id,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _cleanup(*, job_ids: list[int], user_ids: list[int]) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.user import User
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for jid in job_ids:
            await db.execute(delete(Job).where(Job.id == jid))
        for uid in user_ids:
            await db.execute(delete(User).where(User.id == uid))
        await db.commit()


@pytest.mark.asyncio
async def test_jobs_status_filter_accepts_multiple_values(
    app_client: AsyncClient, app_auth_headers: dict
):
    pub = await _seed_job(status="published")
    drf = await _seed_job(status="draft")
    cls = await _seed_job(status="closed")
    try:
        r = await app_client.get(
            "/api/jobs?status=published&status=draft&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert pub in ids
        assert drf in ids
        assert cls not in ids
    finally:
        await _cleanup(job_ids=[pub, drf, cls], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_status_single_value_back_compat(
    app_client: AsyncClient, app_auth_headers: dict
):
    pub = await _seed_job(status="published")
    drf = await _seed_job(status="draft")
    try:
        r = await app_client.get(
            "/api/jobs?status=published&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert pub in ids
        assert drf not in ids
    finally:
        await _cleanup(job_ids=[pub, drf], user_ids=[])


@pytest.mark.asyncio
async def test_jobs_owner_id_filter_accepts_multiple(
    app_client: AsyncClient, app_auth_headers: dict
):
    u1 = await _seed_user()
    u2 = await _seed_user()
    j1 = await _seed_job(status="published", recruiter_id=u1)
    j2 = await _seed_job(status="published", recruiter_id=u2)
    j_orphan = await _seed_job(status="published", recruiter_id=None)
    try:
        r = await app_client.get(
            f"/api/jobs?owner_id={u1}&owner_id={u2}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = {item["id"] for item in r.json()["items"]}
        assert j1 in ids
        assert j2 in ids
        assert j_orphan not in ids
    finally:
        await _cleanup(job_ids=[j1, j2, j_orphan], user_ids=[u1, u2])
