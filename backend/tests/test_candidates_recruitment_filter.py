"""Tests for `GET /api/candidates?recruitment_id=...&recruitment_match=...`.

Filters candidates by assignment (or lack of it) to specific recruitments
(jobs). "Assigned" mirrors talent-pool membership: a candidate counts when they
have ANY `candidate_stages` row for the job — any stage, including terminal
(`rejected`/`withdrawn`) — distinct from the `employment` filter which only
counts a LATEST `hired` stage.

* `recruitment_match=assigned` (default) — in the pipeline of ANY selected job.
* `recruitment_match=not_assigned`        — in NONE of the selected jobs.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, name_suffix: str = "") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Recr",
            lastname=f"Test-{uuid.uuid4().hex[:6]}{name_suffix}",
            email=f"recr-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> tuple[int, int]:
    """Create a Client + Job. Returns (job_id, client_id)."""
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"RecrClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Recr-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id, cli.id


async def _seed_stage(candidate_id: int, job_id: int, stage_value: str) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStage(
                candidate_id=candidate_id,
                job_id=job_id,
                stage=PipelineStage(stage_value),
            )
        )
        await db.commit()


async def _cleanup(
    *, candidate_ids: list[int], job_ids: list[int], client_ids: list[int]
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.client import Client
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for jid in job_ids:
            await db.execute(delete(CandidateStage).where(CandidateStage.job_id == jid))
            await db.execute(delete(Job).where(Job.id == jid))
        for cli in client_ids:
            await db.execute(delete(Client).where(Client.id == cli))
        await db.commit()


def _ids(payload: dict) -> list[int]:
    return [it["id"] for it in payload["items"]]


@pytest.mark.asyncio
async def test_assigned_includes_only_pipeline_members(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_id={job}` (assigned default) returns the candidate in that
    job's pipeline and excludes one who is not."""
    job_id, client_id = await _seed_job()
    member = await _seed_candidate(name_suffix="-M")
    outsider = await _seed_candidate(name_suffix="-O")
    await _seed_stage(member, job_id, "screening")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert member in ids, "candidate in the pipeline must match"
        assert outsider not in ids, "candidate not in the pipeline must not match"
    finally:
        await _cleanup(
            candidate_ids=[member, outsider],
            job_ids=[job_id],
            client_ids=[client_id],
        )


@pytest.mark.asyncio
async def test_not_assigned_is_complement(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_match=not_assigned` is the exact complement — the pipeline
    member drops out, the outsider stays in."""
    job_id, client_id = await _seed_job()
    member = await _seed_candidate(name_suffix="-M")
    outsider = await _seed_candidate(name_suffix="-O")
    await _seed_stage(member, job_id, "screening")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}"
            "&recruitment_match=not_assigned&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert member not in ids, "pipeline member must NOT match not_assigned"
        assert outsider in ids, "non-member must match not_assigned"
    finally:
        await _cleanup(
            candidate_ids=[member, outsider],
            job_ids=[job_id],
            client_ids=[client_id],
        )


@pytest.mark.asyncio
async def test_assigned_or_combines_multiple_recruitments(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Multiple `recruitment_id` values are OR-combined: a candidate in EITHER
    job's pipeline matches; one in neither does not."""
    job_a, client_a = await _seed_job()
    job_b, client_b = await _seed_job()
    in_a = await _seed_candidate(name_suffix="-A")
    in_b = await _seed_candidate(name_suffix="-B")
    in_neither = await _seed_candidate(name_suffix="-N")
    await _seed_stage(in_a, job_a, "new")
    await _seed_stage(in_b, job_b, "new")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_a}&recruitment_id={job_b}"
            "&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = _ids(r.json())
        assert in_a in ids and in_b in ids, "either-pipeline candidates match"
        assert in_neither not in ids, "candidate in neither pipeline must not match"
    finally:
        await _cleanup(
            candidate_ids=[in_a, in_b, in_neither],
            job_ids=[job_a, job_b],
            client_ids=[client_a, client_b],
        )


@pytest.mark.asyncio
async def test_assigned_counts_terminal_stage(
    app_client: AsyncClient, app_auth_headers: dict
):
    """ "Assigned" means present in the pipeline at ANY stage — a candidate whose
    only stage is terminal (`rejected`) still counts (unlike employment=at_client)."""
    job_id, client_id = await _seed_job()
    rejected = await _seed_candidate(name_suffix="-R")
    await _seed_stage(rejected, job_id, "rejected")
    try:
        r = await app_client.get(
            f"/api/candidates?recruitment_id={job_id}&page_size=100",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        assert rejected in _ids(r.json()), "rejected-stage candidate is still assigned"
    finally:
        await _cleanup(
            candidate_ids=[rejected], job_ids=[job_id], client_ids=[client_id]
        )


@pytest.mark.asyncio
async def test_recruitment_match_invalid_value_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`recruitment_match` only accepts `assigned`/`not_assigned`."""
    r = await app_client.get(
        "/api/candidates?recruitment_id=1&recruitment_match=bogus",
        headers=app_auth_headers,
    )
    assert r.status_code == 422, r.text
