"""Tests for denormalized `client_name` on /api/jobs (list + detail).

Kolumna "Klient" na liście ofert czyta `job.client_name` — backend musi
zwracać nazwę klienta (coalesce(display_name, name), spójnie z
/api/clients-lookup) bez dodatkowego fetcha per job.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_client(*, name: str, display_name: str | None = None) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client

    async with AsyncSessionLocal() as db:
        c = Client(name=name, display_name=display_name)
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job(client_id: int) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        j = Job(
            title=f"ClientNameJob-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=client_id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _cleanup(*, job_ids: list[int], client_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        for jid in job_ids:
            await db.execute(delete(Job).where(Job.id == jid))
        for cid in client_ids:
            await db.execute(delete(Client).where(Client.id == cid))
        await db.commit()


@pytest.mark.asyncio
async def test_jobs_list_returns_client_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_name = f"CN-Client-{uuid.uuid4().hex[:6]}"
    cid = await _seed_client(name=client_name)
    jid = await _seed_job(cid)
    try:
        r = await app_client.get(
            f"/api/jobs?client_id={cid}&page_size=100", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        items = {item["id"]: item for item in r.json()["items"]}
        assert jid in items
        assert items[jid]["client_name"] == client_name
    finally:
        await _cleanup(job_ids=[jid], client_ids=[cid])


@pytest.mark.asyncio
async def test_jobs_list_client_name_prefers_display_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    display = f"CN-Display-{uuid.uuid4().hex[:6]}"
    cid = await _seed_client(
        name=f"CN-Raw-{uuid.uuid4().hex[:6]}", display_name=display
    )
    jid = await _seed_job(cid)
    try:
        r = await app_client.get(
            f"/api/jobs?client_id={cid}&page_size=100", headers=app_auth_headers
        )
        assert r.status_code == 200, r.text
        items = {item["id"]: item for item in r.json()["items"]}
        assert jid in items
        assert items[jid]["client_name"] == display
    finally:
        await _cleanup(job_ids=[jid], client_ids=[cid])


@pytest.mark.asyncio
async def test_job_detail_returns_client_name(
    app_client: AsyncClient, app_auth_headers: dict
):
    client_name = f"CN-Detail-{uuid.uuid4().hex[:6]}"
    cid = await _seed_client(name=client_name)
    jid = await _seed_job(cid)
    try:
        r = await app_client.get(f"/api/jobs/{jid}", headers=app_auth_headers)
        assert r.status_code == 200, r.text
        assert r.json()["client_name"] == client_name
    finally:
        await _cleanup(job_ids=[jid], client_ids=[cid])
