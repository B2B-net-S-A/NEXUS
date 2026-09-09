"""P0-A: ProposalSnapshot records + exposes the degraded-semantic flag.

`compute_proposal_for_job` computes `semantic_degraded` (Qdrant/Voyage down or
the job unindexed → neutral-semantic DB fallback) but previously discarded it, so
a fallback ranking was indistinguishable from a healthy one. It is now persisted
on the snapshot and surfaced by the proposals API for the UI to flag.

The retrieval + scoring stack is monkeypatched so these tests isolate the
degraded-flag logic (no Qdrant/Voyage, no real scoring).
"""

from __future__ import annotations

import uuid

from httpx import AsyncClient

from app.core.database import AsyncSessionLocal


async def _seed_job() -> int:
    from app.models.client import Client
    from app.models.job import Job, JobStatus

    async with AsyncSessionLocal() as db:
        cli = Client(name=f"DegradedClient-{uuid.uuid4().hex[:6]}")
        db.add(cli)
        await db.commit()
        await db.refresh(cli)
        job = Job(
            title=f"Degraded-Job-{uuid.uuid4().hex[:6]}",
            status=JobStatus.published,
            client_id=cli.id,
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job.id


async def _seed_candidate() -> int:
    from app.models.candidate import Candidate, CandidateStatus

    async with AsyncSessionLocal() as db:
        c = Candidate(
            name="Deg",
            lastname=f"Cand-{uuid.uuid4().hex[:6]}",
            email=f"deg-{uuid.uuid4().hex[:8]}@example.com",
            status=CandidateStatus.active,
        )
        db.add(c)
        await db.commit()
        await db.refresh(c)
        return c.id


def _patch_stack(monkeypatch, *, hits):
    """Stub retrieval (return ``hits``), embedding, and scoring."""
    from app.services import embedding_service, canonical_fit

    async def _search(*_a, **_k):
        return hits

    async def _noop_embed(*_a, **_k):
        return None

    async def _no_scores(*_a, **_k):
        return []

    monkeypatch.setattr(embedding_service, "search_candidates_semantic", _search)
    monkeypatch.setattr(embedding_service, "embed_job", _noop_embed)
    monkeypatch.setattr(canonical_fit, "score_candidates", _no_scores)


async def _run_compute(job_id: int):
    from app.models.proposal_snapshot import ProposalSnapshot
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    snap_id = await create_pending_snapshot(job_id, source="create")
    await compute_proposal_for_job(snap_id, job_id)
    async with AsyncSessionLocal() as db:
        return await db.get(ProposalSnapshot, snap_id)


async def test_compute_persists_degraded_when_semantic_empty(monkeypatch):
    _patch_stack(monkeypatch, hits=[])  # Qdrant empty → degraded fallback
    job_id = await _seed_job()
    await _seed_candidate()

    snap = await _run_compute(job_id)

    assert snap.status == "ready"
    assert snap.degraded is True


async def test_compute_not_degraded_when_semantic_has_hits(monkeypatch):
    cand_id = await _seed_candidate()
    _patch_stack(monkeypatch, hits=[{"candidate_id": cand_id, "score": 0.9}])
    job_id = await _seed_job()

    snap = await _run_compute(job_id)

    assert snap.status == "ready"
    assert snap.degraded is False


async def test_latest_proposal_exposes_degraded(
    app_client: AsyncClient, app_auth_headers: dict
):
    from app.models.proposal_snapshot import ProposalSnapshot

    job_id = await _seed_job()
    async with AsyncSessionLocal() as db:
        db.add(
            ProposalSnapshot(
                job_id=job_id,
                source="create",
                status="ready",
                top_k=20,
                degraded=True,
                candidate_ids=[],
                breakdowns=[],
            )
        )
        await db.commit()

    resp = await app_client.get(
        f"/api/jobs/{job_id}/proposals/latest", headers=app_auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["degraded"] is True
