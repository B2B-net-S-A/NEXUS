"""P0-B: proposal snapshots carry run_id + fingerprint and go stale on edits.

A snapshot never recorded which brief/Champion revision produced it, nor whether
that revision later changed — so an outdated ranking looked current. Now a fresh
compute stamps run_id + input_fingerprint (and stale=False), and a later
brief/Champion edit flips the latest snapshot's stale flag so the UI can prompt
a re-run.
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal

_READY_CHAMPION = {
    "project_context": {"about": "Platforma B2B", "responsibilities": "Backend"},
    "screening_questions": [
        {"id": "q1", "question": "Python?"},
        {"id": "q2", "question": "Postgres?"},
    ],
}


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"FreshClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Fresh-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_ready_snapshot(job_id: int) -> int:
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        snap = ProposalSnapshot(
            job_id=job_id,
            source="handoff",
            status="ready",
            top_k=20,
            stale=False,
            run_id="seed",
            candidate_ids=[],
            breakdowns=[],
        )
        db.add(snap)
        await db.commit()
        await db.refresh(snap)
        return snap.id


async def _snapshot(snap_id: int):
    from app.models.proposal_snapshot import ProposalSnapshot

    async with AsyncSessionLocal() as db:
        return await db.get(ProposalSnapshot, snap_id)


async def test_compute_stamps_run_id_fingerprint_and_clears_stale(monkeypatch):
    from app.services import embedding_service, match_score_cache
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    async def _empty(*_a, **_k):
        return []

    async def _noop(*_a, **_k):
        return None

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _empty)
    monkeypatch.setattr(embedding_service, "embed_job", _noop)
    monkeypatch.setattr(match_score_cache, "bulk_get_or_compute", _empty)

    job_id = await _seed_job()
    snap_id = await create_pending_snapshot(job_id, source="handoff")
    await compute_proposal_for_job(snap_id, job_id)

    snap = await _snapshot(snap_id)
    assert snap.status == "ready"
    assert snap.run_id and len(snap.run_id) >= 8  # minted at create
    assert snap.input_fingerprint  # stamped at compute
    assert snap.stale is False


async def test_champion_edit_marks_latest_snapshot_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job()
    snap_id = await _seed_ready_snapshot(job_id)

    resp = await app_client.put(
        f"/api/jobs/{job_id}/champion-profile",
        headers=app_auth_headers,
        json=_READY_CHAMPION,
    )
    assert resp.status_code == 200, resp.text

    snap = await _snapshot(snap_id)
    assert snap.stale is True


async def test_brief_edit_marks_latest_snapshot_stale(
    app_client: AsyncClient, app_auth_headers: dict
):
    job_id = await _seed_job()
    snap_id = await _seed_ready_snapshot(job_id)

    resp = await app_client.patch(
        f"/api/jobs/{job_id}",
        headers=app_auth_headers,
        json={"title": f"Fresh-Job-renamed-{uuid.uuid4().hex[:6]}"},
    )
    assert resp.status_code == 200, resp.text

    snap = await _snapshot(snap_id)
    assert snap.stale is True


async def test_untouched_snapshot_stays_fresh(
    app_client: AsyncClient, app_auth_headers: dict
):
    # A non-matching edit (e.g. reading the champion) must not stale the ranking.
    job_id = await _seed_job()
    snap_id = await _seed_ready_snapshot(job_id)

    resp = await app_client.get(
        f"/api/jobs/{job_id}/champion-profile", headers=app_auth_headers
    )
    assert resp.status_code == 200, resp.text

    snap = await _snapshot(snap_id)
    assert snap.stale is False
