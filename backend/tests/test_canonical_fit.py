from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import canonical_fit as fit
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
async def test_batch_and_pair_have_same_score_and_unknown_is_not_numeric(monkeypatch):
    candidates = [make_candidate(id=i, skills=["Python"]) for i in [2, 1, 3]]
    context = build_request_context(
        make_job(description="intro " * 3000 + "Required: Django"), DEFAULT_PROFILE
    )
    query = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(fit, "request_vector", query)
    measurements = {
        1: VectorMeasurement(0.8, "measured"),
        2: VectorMeasurement(0.8, "measured"),
        3: VectorMeasurement(None, "missing_index"),
    }
    monkeypatch.setattr(fit, "measure_candidates", AsyncMock(return_value=measurements))
    results = await fit.score_candidates(None, context, candidates)
    direct = await fit.score_pair(None, context, candidates[0], measurements[2])
    assert [r.breakdown.candidate_id for r in results] == [1, 2, 3]
    assert results[1].fit_score == direct.fit_score
    assert results[-1].fit_score is None and results[-1].as_dict()["total"] is None
    assert results[1].breakdown.champion_fit.points == 0
    assert query.call_args.args[0] == context.query_text
    assert "Required: Django" in query.call_args.args[0]


@pytest.mark.asyncio
async def test_recommendations_remeasure_retrieval_scores_and_keep_unknown(monkeypatch):
    from app.api import recommendations as api
    from app.services import match_score_cache

    job = make_job(description="full request " * 2000)
    candidates = [
        make_candidate(
            id=i,
            name="Test",
            lastname="Candidate",
            email=None,
            phone=None,
            status=SimpleNamespace(value="active"),
            competence_category=None,
            years_it_experience=None,
            champion=False,
            avatar_url=None,
            tags=[],
            ai_summary=None,
        )
        for i in [1, 2]
    ]
    db = AsyncMock()
    db.scalar.return_value = job
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: candidates)
    )
    monkeypatch.setattr(
        api, "resolve_active_profile", AsyncMock(return_value=DEFAULT_PROFILE)
    )
    monkeypatch.setattr(
        api, "resolve_delivery_lead_client_ids", AsyncMock(return_value=None)
    )
    monkeypatch.setattr(api, "assert_delivery_lead_client_visible", lambda *_: None)
    monkeypatch.setattr(
        api,
        "retrieve_candidate_pool",
        AsyncMock(
            return_value=[
                {"candidate_id": 1, "score": 0.99},
                {"candidate_id": 2, "score": 0.99},
            ]
        ),
    )
    monkeypatch.setattr(
        api, "fetch_historical_boost_map", AsyncMock(return_value={1: 8})
    )
    monkeypatch.setattr(
        api,
        "filter_eligible_candidates",
        AsyncMock(return_value=candidates),
    )
    legacy = AsyncMock(side_effect=AssertionError("legacy cache must not be touched"))
    monkeypatch.setattr(match_score_cache, "bulk_get_or_compute", legacy)
    monkeypatch.setattr(fit, "request_vector", AsyncMock(return_value=[1, 0]))
    monkeypatch.setattr(
        fit,
        "measure_candidates",
        AsyncMock(
            return_value={
                1: VectorMeasurement(0.1, "measured"),
                2: VectorMeasurement(None, "stale"),
            }
        ),
    )
    result = await api._recommend_candidates_core(
        1,
        current_user=SimpleNamespace(id=1),
        db=db,
        min_score=0,
        include_breakdown=False,
        exclude_in_pipeline=False,
    )
    direct = await fit.score_pair(
        None,
        build_request_context(job, DEFAULT_PROFILE),
        candidates[0],
        VectorMeasurement(0.1, "measured"),
    )
    assert result["matches"][0]["total_score"] == direct.fit_score
    assert result["matches"][1]["total_score"] is None
    assert result["matches"][1]["measurement"] == "stale"
    assert result["meta"]["degraded"]
    legacy.assert_not_called()


def test_snapshot_hydration_preserves_unknown_score():
    from app.api.proposals import _hydrate_items
    from app.models.candidate import Candidate

    snapshot = SimpleNamespace(
        breakdowns=[{"candidate_id": 7, "total": None, "measurement": "missing_index"}]
    )
    rows = _hydrate_items(
        snapshot, {7: Candidate(id=7, name="Test", lastname="Candidate")}
    )
    assert len(rows) == 1
    assert rows[0].total_score is None
    assert rows[0].breakdown["measurement"] == "missing_index"
