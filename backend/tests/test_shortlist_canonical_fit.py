from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.api import job_shortlist
from app.services import canonical_fit, scoring_service
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
async def test_shortlist_current_fit_matches_pair_and_keeps_archive_separate(
    monkeypatch,
):
    monkeypatch.setattr(
        "app.services.requirement_verification.latest_verifications",
        AsyncMock(return_value=[]),
    )
    job = make_job(id=7, client_id=8, description="X" * 9000 + "Django")
    candidates = [
        make_candidate(id=i, name="Test", lastname="Candidate") for i in [1, 2]
    ]
    entries = [
        SimpleNamespace(
            id=i,
            job_id=7,
            candidate_id=i,
            evaluation_status="do_oceny",
            outreach_status="nie_kontaktowano",
            version=1,
            score_snapshot=99,
        )
        for i in [1, 2]
    ]
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(
        all=lambda: list(zip(entries, candidates))
    )
    db.scalar.return_value = job
    monkeypatch.setattr(job_shortlist, "ensure_job_read_access", AsyncMock())
    profile = AsyncMock(return_value=DEFAULT_PROFILE)
    monkeypatch.setattr(scoring_service, "resolve_active_profile", profile)
    query = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(canonical_fit, "request_vector", query)
    measurements = {
        1: VectorMeasurement(0.1, "measured"),
        2: VectorMeasurement(None, "missing_index"),
    }
    monkeypatch.setattr(
        canonical_fit, "measure_candidates", AsyncMock(return_value=measurements)
    )
    rows = await job_shortlist.list_shortlist(
        7, current_user=SimpleNamespace(id=42), db=db
    )
    expected = await canonical_fit.score_pair(
        db, build_request_context(job, DEFAULT_PROFILE), candidates[0], measurements[1]
    )
    assert rows[0].fit_score == expected.fit_score
    assert rows[0].score_snapshot == 99
    assert rows[1].fit_score is None and rows[1].fit_measurement == "missing_index"
    assert rows[0].fit_context_fingerprint == rows[1].fit_context_fingerprint
    assert "Django" in query.call_args.args[0]
    profile.assert_awaited_once_with(db, user_id=42, client_id=8)
