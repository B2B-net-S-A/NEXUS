"""Snapshot propozycji musi rankować TYM SAMYM wzorem co `/recommendations`.

Widget „Sugerowani kandydaci" startuje w trybie snapshot i przełącza się na
żywy endpoint dopiero po włączeniu filtra. Żywa ścieżka dokłada boost
historyczny PRZED odcięciem po `RECOMMENDATION_MIN_SCORE`, snapshot nie
dokładał go wcale — więc kandydat sprawdzony już na trzech podobnych
projektach (28 + 15 = 43 przy progu 40) pojawiał się po wpisaniu miasta
i znikał po wyczyszczeniu filtra, bez żadnej wskazówki, że to dwa różne wzory.

Regresja jest CICHA: obie listy wyglądają poprawnie, różnią się składem.
"""

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
async def test_snapshot_applies_historical_boost_before_the_min_score_cut(
    boost_fixture,
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
        # 28 < RECOMMENDATION_MIN_SCORE (40) — bez boostu ten kandydat wypada.
        return [_breakdown(cand_id, job_id, 28.0)]

    with (
        patch("app.tasks.compute_proposals.retrieve_candidate_pool", new=_pool),
        patch("app.services.match_score_cache.bulk_get_or_compute", new=_scored),
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
        assert snap.candidate_ids == [cand_id], (
            "kandydat sprawdzony na podobnych projektach wypadł ze snapshotu, "
            "choć na żywym /recommendations przechodzi próg"
        )
        payload = snap.breakdowns[0]
        assert payload["historical_boost"] == 15.0
        assert payload["historical_sources_count"] == 3
        assert payload["total"] == 43.0


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
        return [_breakdown(cand_id, job_id, 55.0)]

    async def _boom(*_a, **_kw):
        raise RuntimeError("qdrant down")

    with (
        patch("app.tasks.compute_proposals.retrieve_candidate_pool", new=_pool),
        patch("app.services.match_score_cache.bulk_get_or_compute", new=_scored),
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
