"""Tests for `GET /api/candidates?pipeline_stage=…&stage_category=…&stage_current_only=…`.

Filter semantics:

* `pipeline_stage` — multi-select OR over PipelineStage enum values.
* `stage_category` — coarse-grained OR over internal/external/terminal,
  expanded to the same enum value space and combined with `pipeline_stage`
  via OR.
* `stage_current_only` (default True) — match the LATEST stage per
  `(candidate_id, job_id)` pair. When False, match any historical move.

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient


async def _seed_candidate(*, name_suffix: str = "") -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Stage",
            lastname=f"Test-{uuid.uuid4().hex[:6]}{name_suffix}",
            email=f"stage-{uuid.uuid4().hex[:8]}@example.com",
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


async def _seed_job() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"StageClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Stage-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(
    candidate_id: int,
    job_id: int,
    stage_value: str,
    *,
    moved_at: datetime | None = None,
) -> int:
    """Insert a CandidateStage row at the given pipeline stage.

    `moved_at` controls ordering — pass increasing timestamps when seeding
    multiple moves for the same `(candidate_id, job_id)` pair so the
    DISTINCT-ON-based "current stage" lookup is deterministic.
    """
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=moved_at or datetime.now(timezone.utc),
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _cleanup(
    *,
    candidate_ids: list[int] | None = None,
    job_ids: list[int] | None = None,
) -> None:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate
    from app.models.job import Job
    from app.models.recruitment_pipeline import CandidateStage
    from sqlalchemy import delete

    async with AsyncSessionLocal() as db:
        for cid in candidate_ids or []:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.candidate_id == cid)
            )
            await db.execute(delete(Candidate).where(Candidate.id == cid))
        for jid in job_ids or []:
            await db.execute(
                delete(CandidateStage).where(CandidateStage.job_id == jid)
            )
            await db.execute(delete(Job).where(Job.id == jid))
        await db.commit()


@pytest.mark.asyncio
async def test_filter_pipeline_stage_single_value(
    app_client: AsyncClient, app_auth_headers: dict
):
    """A candidate currently at `screening` shows up; one at `new` doesn't."""
    job_id = await _seed_job()
    target = await _seed_candidate(name_suffix="-A")
    other = await _seed_candidate(name_suffix="-B")
    await _seed_stage(target, job_id, "screening")
    await _seed_stage(other, job_id, "new")
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert target in ids
        assert other not in ids
    finally:
        await _cleanup(candidate_ids=[target, other], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_pipeline_stage_multi_value_or(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Multiple `pipeline_stage` params OR-combine — both candidates match."""
    job_id = await _seed_job()
    at_screening = await _seed_candidate(name_suffix="-S")
    at_interview = await _seed_candidate(name_suffix="-I")
    at_new = await _seed_candidate(name_suffix="-N")
    await _seed_stage(at_screening, job_id, "screening")
    await _seed_stage(at_interview, job_id, "interview")
    await _seed_stage(at_new, job_id, "new")
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening"
            "&pipeline_stage=interview&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert at_screening in ids
        assert at_interview in ids
        assert at_new not in ids
    finally:
        await _cleanup(
            candidate_ids=[at_screening, at_interview, at_new], job_ids=[job_id]
        )


@pytest.mark.asyncio
async def test_filter_stage_current_only_true_default(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_current_only=true` (default) ignores historical `screening` row
    when the latest move is `rejected` — candidate must NOT appear when
    filtering for `screening`."""
    job_id = await _seed_job()
    cand = await _seed_candidate()
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(cand, job_id, "screening", moved_at=base)
    await _seed_stage(
        cand, job_id, "rejected", moved_at=base + timedelta(days=1)
    )
    try:
        # Default behaviour — latest move is `rejected`, so `screening` query
        # must NOT include this candidate.
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert cand not in ids

        # But the same candidate IS at `rejected`, so the rejected query hits.
        r2 = await app_client.get(
            "/api/candidates?pipeline_stage=rejected&page_size=200",
            headers=app_auth_headers,
        )
        ids2 = [item["id"] for item in r2.json()["items"]]
        assert cand in ids2
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_stage_current_only_false_matches_history(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_current_only=false` matches any historical move — candidate
    that was once at `screening` (even though now `rejected`) IS returned."""
    job_id = await _seed_job()
    cand = await _seed_candidate()
    base = datetime.now(timezone.utc) - timedelta(days=10)
    await _seed_stage(cand, job_id, "screening", moved_at=base)
    await _seed_stage(
        cand, job_id, "rejected", moved_at=base + timedelta(days=1)
    )
    try:
        r = await app_client.get(
            "/api/candidates?pipeline_stage=screening"
            "&stage_current_only=false&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert cand in ids
    finally:
        await _cleanup(candidate_ids=[cand], job_ids=[job_id])


@pytest.mark.asyncio
async def test_filter_stage_category_external_expands_to_stages(
    app_client: AsyncClient, app_auth_headers: dict
):
    """`stage_category=external` matches client_interview/acceptance/
    negotiation/onboarding — candidate at `client_interview` is returned,
    one at `screening` (internal) is not."""
    job_id = await _seed_job()
    at_client_interview = await _seed_candidate(name_suffix="-X")
    at_screening = await _seed_candidate(name_suffix="-S")
    await _seed_stage(at_client_interview, job_id, "client_interview")
    await _seed_stage(at_screening, job_id, "screening")
    try:
        r = await app_client.get(
            "/api/candidates?stage_category=external&page_size=200",
            headers=app_auth_headers,
        )
        assert r.status_code == 200, r.text
        ids = [item["id"] for item in r.json()["items"]]
        assert at_client_interview in ids
        assert at_screening not in ids
    finally:
        await _cleanup(
            candidate_ids=[at_client_interview, at_screening], job_ids=[job_id]
        )


@pytest.mark.asyncio
async def test_filter_invalid_stage_returns_422(
    app_client: AsyncClient, app_auth_headers: dict
):
    """FastAPI enum validation rejects non-enum stage values with 422."""
    r = await app_client.get(
        "/api/candidates?pipeline_stage=bogus_stage&page_size=10",
        headers=app_auth_headers,
    )
    assert r.status_code == 422
