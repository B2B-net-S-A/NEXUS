"""Jobs API smoke tests — in-process client, own seeded data.

Ported from the live-server suite, which assumed a running backend with jobs
already in its database.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import AsyncSessionLocal


async def _seed_job() -> tuple[int, str]:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    tag = uuid.uuid4().hex[:8]
    title = f"JobsSmoke {tag}"
    async with AsyncSessionLocal() as db:
        client = Client(name=f"JobsSmoke client {tag}")
        db.add(client)
        await db.flush()
        job = Job(title=title, status=JobStatus.published, client_id=client.id)
        db.add(job)
        await db.commit()
        return job.id, title


async def test_list_jobs_includes_candidate_counts(
    app_client: AsyncClient, app_auth_headers: dict
):
    await _seed_job()
    resp = await app_client.get("/api/jobs", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "items" in data
    assert data["total"] > 0
    assert data["items"]
    for job in data["items"]:
        assert isinstance(job["candidate_count"], int)


async def test_get_job(app_client: AsyncClient, app_auth_headers: dict):
    job_id, title = await _seed_job()
    resp = await app_client.get(f"/api/jobs/{job_id}", headers=app_auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == job_id
    assert resp.json()["title"] == title


async def test_job_not_found(app_client: AsyncClient, app_auth_headers: dict):
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        missing = (await db.scalar(select(func.max(Job.id))) or 0) + 100_000
    resp = await app_client.get(f"/api/jobs/{missing}", headers=app_auth_headers)
    assert resp.status_code == 404


async def test_jobs_unauthorized(app_client: AsyncClient):
    resp = await app_client.get("/api/jobs")
    assert resp.status_code == 401
