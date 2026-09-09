"""Snapshot handoffu (compute_proposals) egzekwuje rubryki 0278 tak samo jak
`/recommendations` — `dealbreaker_inputs_for_job` jest WSPÓLNE dla obu.

Bez tego DOMYŚLNY widok zakładki (snapshot) i żywe zapytanie z filtrami
liczyłyby ukrywanie inaczej, a rekruter dostawałby dwie różne odpowiedzi na
to samo pytanie „kogo widać dla tej oferty".
"""

from __future__ import annotations

import uuid
from unittest.mock import patch

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from app.core.database import AsyncSessionLocal
from app.models.candidate import Candidate, CandidateStatus
from app.models.client import Client
from app.models.job import Job
from app.models.proposal_snapshot import ProposalSnapshot, STATUS_READY


@pytest_asyncio.fixture
async def rubric_gate_fixture():
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        client = Client(name=f"ProposalRubric Client {unique}")
        db.add(client)
        await db.flush()
        job = Job(
            title=f"ProposalRubric Job {unique}",
            client_id=client.id,
            description="Python backend engineer, 3 dni w biurze",
            requirements="python",
            hiring_manager_contact_id=None,
            # Ustawione, żeby task nie wołał `embed_job` (i Voyage'a) na starcie.
            embedding_id="test-embedding",
            must_skills=[{"name": "python"}],
            requirements_reviewed=True,
            matching_requirements={
                "reviewed": True,
                "missing_evidence_policy": "exclude",
                "all_of": [{"any_of": ["python"], "level": "must"}],
            },
            onsite_days_per_week=3,
        )
        missing_must = Candidate(
            name="BrakMust",
            lastname=f"Kandydat{unique}",
            email=f"missing-must-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "java"}],
            max_onsite_days_per_week=5,  # spełnia dni, nie ma must-have
        )
        exceeds_days = Candidate(
            name="ZaMaloDni",
            lastname=f"Kandydat{unique}",
            email=f"exceeds-days-{unique}@example.com",
            status=CandidateStatus.active,
            skills=[{"name": "python"}],  # spełnia must
            max_onsite_days_per_week=1,  # 1 < 3 wymaganych
        )
        db.add_all([job, missing_must, exceeds_days])
        await db.commit()
        ids = (job.id, missing_must.id, exceeds_days.id, client.id)

    yield ids

    job_id, missing_must_id, exceeds_days_id, client_id = ids
    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(ProposalSnapshot).where(ProposalSnapshot.job_id == job_id)
        )
        await db.execute(
            delete(Candidate).where(
                Candidate.id.in_([missing_must_id, exceeds_days_id])
            )
        )
        await db.execute(delete(Job).where(Job.id == job_id))
        await db.execute(delete(Client).where(Client.id == client_id))
        await db.commit()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_snapshot_hides_missing_must_and_office_days_exceeded(
    rubric_gate_fixture,
):
    from app.tasks.compute_proposals import (
        compute_proposal_for_job,
        create_pending_snapshot,
    )

    job_id, missing_must_id, exceeds_days_id, _client_id = rubric_gate_fixture
    snapshot_id = await create_pending_snapshot(job_id, source="manual_regenerate")

    async def _pool(*_a, **_kw):
        return [
            {"candidate_id": missing_must_id, "score": 0.8},
            {"candidate_id": exceeds_days_id, "score": 0.7},
        ]

    with patch("app.tasks.compute_proposals.retrieve_candidate_pool", new=_pool):
        await compute_proposal_for_job(snapshot_id, job_id, top_k=10)

    async with AsyncSessionLocal() as db:
        snap = await db.scalar(
            select(ProposalSnapshot).where(ProposalSnapshot.id == snapshot_id)
        )
        assert snap is not None
        assert snap.status == STATUS_READY, snap.error_message
        # Obaj kandydaci odpadają PRZED scoringiem — żaden nie trafia do
        # rankingu (bulk_get_or_compute nigdy nie widzi pustej listy).
        assert snap.candidate_ids == []
        assert snap.hidden["missing_must"] == 1
        assert snap.hidden["office_days_exceeded"] == 1
        assert snap.hidden["over_budget"] == 0
        assert snap.hidden["office_city_mismatch"] == 0
        assert snap.hidden["remote_only"] == 0
