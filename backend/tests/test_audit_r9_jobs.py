"""Runda 9 audytu — rekrutacje (kod JOBS).

Testy bez bazy sprawdzają kształt klauzul i schematów; testy z ``app_client``
potrzebują Postgresa (CI). Rejestr rekrutacji jest wspólny dla całej bazy
testowej, więc listy zawężamy unikalnym tokenem w tytule (``q=``).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
from httpx import AsyncClient
from sqlalchemy.dialects import postgresql

# ── Bez bazy ─────────────────────────────────────────────────────────────────


def _sql(clause) -> str:
    return str(
        clause.compile(
            dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}
        )
    )


def test_mine_clause_includes_live_work_assignments() -> None:
    """R9-N15-2: „Moje” widzi request przydzielony w ``job_work_assignments``."""
    from app.api.jobs import jobs_mine_clause, jobs_mine_scope_clause

    user = SimpleNamespace(id=7, roles=["sourcer"], role="sourcer")
    for clause in (jobs_mine_clause(user), jobs_mine_scope_clause(user)):
        sql = _sql(clause)
        assert "job_work_assignments" in sql, sql
        assert "released" in sql, sql


# ── Pomocnicy (baza) ─────────────────────────────────────────────────────────


async def _me_id(app_client: AsyncClient, headers: dict) -> int:
    response = await app_client.get("/api/auth/me", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def _seed_job(token: str, **fields) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        client = Client(name=f"R9Jobs-{uuid.uuid4().hex[:6]}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"{token}-{uuid.uuid4().hex[:4]}",
            status=fields.pop("status", JobStatus.published),
            client_id=client.id,
            **fields,
        )
        db.add(job)
        await db.commit()
        return job.id


async def _assign(job_id: int, user_id: int, state: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        db.add(
            JobWorkAssignment(
                job_id=job_id,
                user_id=user_id,
                role="sourcer",
                source="manual",
                state=state,
                released_at=datetime.now(timezone.utc) if state == "released" else None,
            )
        )
        await db.commit()


async def _cleanup(job_ids: list[int]) -> None:
    from sqlalchemy import delete

    from app.core.database import AsyncSessionLocal
    from app.models.job import Job
    from app.models.job_work_assignment import JobWorkAssignment

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(JobWorkAssignment).where(JobWorkAssignment.job_id.in_(job_ids))
        )
        await db.execute(delete(Job).where(Job.id.in_(job_ids)))
        await db.commit()


async def _ids(app_client: AsyncClient, headers: dict, query: str) -> set[int]:
    response = await app_client.get(f"/api/jobs?page_size=100&{query}", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"] for row in response.json()["items"]}


async def _quick_counts(app_client: AsyncClient, headers: dict) -> dict:
    response = await app_client.get("/api/jobs/quick-counts", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


# ── R9-N15-2 ─────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_mine_scope_lists_and_counts_live_assignments(
    app_client: AsyncClient, app_auth_headers: dict
):
    me = await _me_id(app_client, app_auth_headers)
    token = f"R9Mine{uuid.uuid4().hex[:8]}"
    before = await _quick_counts(app_client, app_auth_headers)
    live = await _seed_job(token)
    released = await _seed_job(token)
    await _assign(live, me, "active")
    await _assign(released, me, "released")
    try:
        mine = await _ids(
            app_client, app_auth_headers, f"q={token}&mine=true&open_only=true"
        )
        assert live in mine
        assert released not in mine
        after = await _quick_counts(app_client, app_auth_headers)
        assert after["mine"] == before["mine"] + 1
    finally:
        await _cleanup([live, released])
