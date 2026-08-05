"""P0-03a: editing a scoring-only field flags the latest snapshot stale.

The re-embed gate (`_EMBED_TRIGGER_FIELDS`) omits location / remote_policy /
deadline because they are absent from `_build_job_text`. But the deterministic
scorer DOES read them (location + availability layers), so reusing the embed set
to gate cache-invalidation + snapshot-stale left a ranking silently stale after
those edits. The fix gates the stale/invalidate path on the wider
`_SCORING_INPUT_FIELDS`. These tests pin that a `location` / `deadline` edit now
marks the latest proposal snapshot stale (it did not before).

Uses the in-process ``app_client`` / ``app_auth_headers`` (admin) fixtures.
"""

from __future__ import annotations

import uuid
from datetime import date

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_job_with_ready_snapshot(**job_kwargs) -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"StaleGate-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"StaleGate-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
            **job_kwargs,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        db.add(
            ProposalSnapshot(
                job_id=job.id,
                source="handoff",
                status="ready",
                top_k=20,
                run_id=uuid.uuid4().hex,
                candidate_ids=[],
                breakdowns=[],
                stale=False,
            )
        )
        await db.commit()
        return job.id


async def _latest_snapshot_stale(job_id: int) -> bool:
    from sqlalchemy import select
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot)
            .where(ProposalSnapshot.job_id == job_id)
            .order_by(ProposalSnapshot.created_at.desc())
            .limit(1)
        )
        return snap.stale


async def test_location_edit_marks_snapshot_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job_with_ready_snapshot(location="Warszawa")
    assert await _latest_snapshot_stale(job_id) is False

    resp = await app_client.patch(
        f"/api/jobs/{job_id}",
        headers=app_auth_headers,
        json={"location": "Kraków"},
    )
    assert resp.status_code == 200, resp.text
    assert await _latest_snapshot_stale(job_id) is True


async def test_deadline_edit_marks_snapshot_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job_with_ready_snapshot(deadline=date(2026, 1, 1))
    assert await _latest_snapshot_stale(job_id) is False

    resp = await app_client.patch(
        f"/api/jobs/{job_id}",
        headers=app_auth_headers,
        json={"deadline": "2026-06-01"},
    )
    assert resp.status_code == 200, resp.text
    assert await _latest_snapshot_stale(job_id) is True
