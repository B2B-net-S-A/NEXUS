"""Tests for `DELETE /api/candidates/{candidate_id}/recruitments/{job_id}`.

Removing a candidate from a recruitment is a corrective action ("added the wrong
candidate / to the wrong job") — distinct from reject/withdrawn, which keep the
candidate in the pipeline at a terminal stage. It deletes ALL `CandidateStage`
rows for the (candidate, job) pair (the append-only stage history) and, via DB
`ON DELETE CASCADE`, the per-recruitment artifacts (CV snapshots → share tokens,
champion-card share tokens, scheduled rejection emails).

Uses the in-process `app_client` / `app_auth_headers` fixtures from conftest
(real postgres in CI).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from httpx import AsyncClient


async def _seed_candidate() -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.candidate import Candidate

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Rm",
            lastname=f"Test-{uuid.uuid4().hex[:6]}",
            email=f"rm-{uuid.uuid4().hex[:8]}@example.com",
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
        cli = Client(name=f"RmClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        j = Job(
            title=f"Rm-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(j)
        await db.commit()
        await db.refresh(j)
        return j.id


async def _seed_stage(candidate_id: int, job_id: int, stage_value: str) -> int:
    from app.core.database import AsyncSessionLocal
    from app.models.recruitment_pipeline import CandidateStage, PipelineStage

    async with AsyncSessionLocal() as db:
        stage = CandidateStage(
            candidate_id=candidate_id,
            job_id=job_id,
            stage=PipelineStage(stage_value),
            moved_at=datetime.now(timezone.utc),
        )
        db.add(stage)
        await db.commit()
        await db.refresh(stage)
        return stage.id


async def _history_job_ids(
    app_client: AsyncClient, headers: dict, candidate_id: int
) -> list[int]:
    r = await app_client.get(
        f"/api/candidates/{candidate_id}/history", headers=headers
    )
    assert r.status_code == 200, r.text
    return [j["job_id"] for j in r.json()["jobs"]]


async def test_remove_from_recruitment_requires_auth(app_client: AsyncClient):
    r = await app_client.delete("/api/candidates/1/recruitments/1")
    # FastAPI HTTPBearer returns 403 when the Authorization header is missing.
    assert r.status_code in (401, 403)


async def test_remove_from_recruitment_404_when_no_recruitment(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    job_id = await _seed_job()  # candidate never added to this job's pipeline

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}/recruitments/{job_id}",
        headers=app_auth_headers,
    )
    assert r.status_code == 404


async def test_remove_from_recruitment_deletes_all_stages(
    app_client: AsyncClient, app_auth_headers: dict
):
    candidate_id = await _seed_candidate()
    job_id = await _seed_job()
    # Append-only history: three stage transitions for the same (candidate, job).
    await _seed_stage(candidate_id, job_id, "new")
    await _seed_stage(candidate_id, job_id, "screening")
    await _seed_stage(candidate_id, job_id, "interview")

    # Precondition: the recruitment shows up in the candidate's history.
    assert job_id in await _history_job_ids(
        app_client, app_auth_headers, candidate_id
    )

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}/recruitments/{job_id}",
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["candidate_id"] == candidate_id
    assert body["job_id"] == job_id
    assert body["removed_stage_count"] == 3

    # The recruitment is gone from history…
    assert job_id not in await _history_job_ids(
        app_client, app_auth_headers, candidate_id
    )
    # …and a second removal is a 404 (nothing left to delete).
    r2 = await app_client.delete(
        f"/api/candidates/{candidate_id}/recruitments/{job_id}",
        headers=app_auth_headers,
    )
    assert r2.status_code == 404


async def test_remove_from_recruitment_cascades_cv_snapshot(
    app_client: AsyncClient, app_auth_headers: dict
):
    """Deleting the stage rows must cascade to the per-recruitment CV snapshot
    (DB `ON DELETE CASCADE` on `candidate_stage_cvs.candidate_stage_id`)."""
    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.candidate_stage_cv import CandidateStageCV

    candidate_id = await _seed_candidate()
    job_id = await _seed_job()
    stage_id = await _seed_stage(candidate_id, job_id, "new")

    async with AsyncSessionLocal() as db:
        db.add(
            CandidateStageCV(
                candidate_stage_id=stage_id,
                candidate_id=candidate_id,
                job_id=job_id,
                original_cv_filename="cv.pdf",
            )
        )
        await db.commit()

    r = await app_client.delete(
        f"/api/candidates/{candidate_id}/recruitments/{job_id}",
        headers=app_auth_headers,
    )
    assert r.status_code == 200, r.text

    async with AsyncSessionLocal() as db:
        remaining = (
            await db.execute(
                select(CandidateStageCV).where(
                    CandidateStageCV.candidate_stage_id == stage_id
                )
            )
        ).scalar_one_or_none()
    assert remaining is None, "CV snapshot should be cascade-deleted with the stage"
