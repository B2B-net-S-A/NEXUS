"""Snapshot history is context, never a way to cross the fit threshold."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job
from app.models.proposal_snapshot import ProposalSnapshot, STATUS_READY
from app.services.scoring_service import LayerResult, ScoreBreakdown
from app.services.canonical_fit import CanonicalFit


def _breakdown(candidate_id: int, job_id: int, total: float) -> ScoreBreakdown:
    neutral = LayerResult(points=0.0, max_points=10.0, reason="test")
    return ScoreBreakdown(
        candidate_id=candidate_id,
        job_id=job_id,
        total=total,
        semantic=neutral,
        skills=neutral,
        salary=neutral,
        location=neutral,
        availability=neutral,
    )


@pytest_asyncio.fixture
async def boost_fixture():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"Boost Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"Boost Job {unique}",
            client_id=client.id,
            description="Python backend engineer",
            requirements="python",
            hiring_manager_contact_id=None,
            # Ustawione, żeby task nie wołał `embed_job` (i Voyage'a) na starcie.
            embedding_id="test-embedding",
        )
        cand = Candidate(
            name="Sprawdzony",
            lastname=f"Kandydat{unique}",
            email=f"boost-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}],
        )
        db.add_all([job, cand])
        await db.commit()
        ids = (job.id, cand.id, client.id)

    yield ids

    job_id, cand_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
        await db.execute(delete(Candidate).where(Candidate.id == cand_id))
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
@pytest.mark.parametrize(
    "base_score, measurement, expected_present",
    [
        (28.0, "measured", False),
        (48.0, "measured", True),
        (28.0, "missing_index", True),
    ],
)
async def test_snapshot_history_does_not_change_fit_threshold(
    boost_fixture,
    base_score,
    measurement,
    expected_present,
):
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    job_id, cand_id, _client_id = boost_fixture
    snapshot_id = await create_pending_snapshot(job_id, source="manual_regenerate")

    async def _pool(*_a, **_kw):
        return [{"candidate_id": cand_id, "score": 0.8}]

    async def _scored(*_a, **_kw):
        return [CanonicalFit(_breakdown(cand_id, job_id, base_score), measurement)]

    with (
        patch("app.tasks.compute_proposals.retrieve_candidate_pool", new=_pool),
        patch("app.services.canonical_fit.score_candidates", new=_scored),
        patch(
            "app.services.similar_job_candidates.fetch_historical_boost_map",
            new=AsyncMock(return_value={cand_id: 3}),
        ),
    ):
        await compute_proposal_for_job(snapshot_id, job_id, top_k=10)

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
        assert snap is not None
        assert snap.status == STATUS_READY, snap.error_message
        assert snap.candidate_ids == ([cand_id] if expected_present else [])
        if expected_present:
            payload = snap.breakdowns[0]
            assert payload["historical_boost"] == 0.0
            assert payload["historical_sources_count"] == 3
            assert payload["total"] == (
                base_score if measurement == "measured" else None
            )
            assert payload["measurement"] == measurement


@pytest.mark.integration
@pytest.mark.asyncio
async def test_boost_lookup_failure_does_not_fail_the_snapshot(boost_fixture):
    """Padnięty lookup podobnych ofert to degradacja rankingu, nie awaria zadania."""
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    job_id, cand_id, _client_id = boost_fixture
    snapshot_id = await create_pending_snapshot(job_id, source="manual_regenerate")

    async def _pool(*_a, **_kw):
        return [{"candidate_id": cand_id, "score": 0.8}]

    async def _scored(*_a, **_kw):
        return [CanonicalFit(_breakdown(cand_id, job_id, 55.0), "measured")]

    async def _boom(*_a, **_kw):
        raise RuntimeError("qdrant down")

    with (
        patch("app.tasks.compute_proposals.retrieve_candidate_pool", new=_pool),
        patch("app.services.canonical_fit.score_candidates", new=_scored),
        patch(
            "app.services.similar_job_candidates.fetch_historical_boost_map", new=_boom
        ),
    ):
        await compute_proposal_for_job(snapshot_id, job_id, top_k=10)

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
        assert snap is not None
        assert snap.status == STATUS_READY, snap.error_message
        assert snap.candidate_ids == [cand_id]
