"""„Moje” obejmuje rekrutacje, których jestem Delivery Leadem (30.09.2026).

Zgłoszenie: DL założyła rekrutację (szkic, bez rekrutera prowadzącego) i na
liście ``/jobs`` w domyślnym dla DL zakresie „Moje” widziała 0. ``jobs_mine_clause``
znał tylko prowadzącego, współpracowników i przydział z pulpitu. Lista ma też
nieść Delivery Leada rozwiniętego do ``UserBrief`` — kafelek pokazuje „DL: …”.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql


def test_mine_clause_includes_delivery_lead() -> None:
    from app.api.jobs import jobs_mine_clause, jobs_mine_scope_clause

    user = SimpleNamespace(id=7, roles=["delivery_lead"], role="delivery_lead")
    for clause in (jobs_mine_clause(user), jobs_mine_scope_clause(user)):
        sql = str(
            clause.compile(
                dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
            )
        )
        assert "jobs.delivery_lead_id" in sql, sql


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _seed_job(token: str, **fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        client = Client(name=f"MineDL-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(title=f"{token}-{uuid.uuid4().hex[:4]}", client_id=client.id, **fields)
        db.add(job)
        await db.commit()
        return job.id


async def _cleanup(job_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job

    async with AsyncSessionLocal() as db:
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


@pytest.mark.asyncio
async def test_draft_led_by_me_is_in_mine_and_carries_delivery_lead(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.job import JobStatus

    me = await _me_id(app_client, app_auth_headers)
    token = f"MineDL{uuid.uuid4().hex[:8]}"
    before = (
        await app_client.get("/api/jobs/quick-counts", headers=app_auth_headers)
    ).json()
    draft = await _seed_job(token, status=JobStatus.draft, delivery_lead_id=me)
    closed = await _seed_job(token, status=JobStatus.closed, delivery_lead_id=me)
    try:
        response = await app_client.get(
            f"/api/jobs?page_size=100&q={token}&mine=true&open_only=true",
            headers=app_auth_headers,
        )
        assert response.status_code == 200, response.text
        rows = {row["id"]: row for row in response.json()["items"]}
        assert draft in rows
        assert closed not in rows
        assert rows[draft]["primary_owner"] is None
        assert rows[draft]["delivery_lead_user"]["id"] == me
        after = (
            await app_client.get("/api/jobs/quick-counts", headers=app_auth_headers)
        ).json()
        assert after["mine"] == before["mine"] + 1
    finally:
        await _cleanup([draft, closed])
