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

    job = make_job(description="full request " * 2000, location="Warszawa")
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
    assert result["location_filter"] is None
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


@pytest.mark.asyncio
async def test_legacy_c2_shared_engine_uses_exact_fit_and_stable_order(monkeypatch):
    from app.api import matching
    from app.services import match_score_cache, scoring_service, similar_job_candidates

    job = make_job(description="X" * 9000 + "TAIL_C2", client_id=8)
    candidates = [
        make_candidate(
            id=i,
            name="Test",
            lastname="Candidate",
            email=None,
            phone=None,
            status=SimpleNamespace(value="active"),
            competence_category=None,
            tags=[],
            ai_summary=None,
            avatar_url=None,
        )
        for i in [3, 2, 1]
    ]
    profile = AsyncMock(return_value=DEFAULT_PROFILE)
    monkeypatch.setattr(scoring_service, "resolve_active_profile", profile)
    monkeypatch.setattr(
        similar_job_candidates,
        "fetch_historical_boost_map",
        AsyncMock(return_value={2: 8}),
    )
    legacy = AsyncMock(side_effect=AssertionError("legacy cache must not be used"))
    monkeypatch.setattr(match_score_cache, "bulk_get_or_compute", legacy)
    query = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(fit, "request_vector", query)
    measurements = {
        1: VectorMeasurement(0.1, "measured"),
        2: VectorMeasurement(0.1, "measured"),
        3: VectorMeasurement(None, "stale"),
    }
    monkeypatch.setattr(fit, "measure_candidates", AsyncMock(return_value=measurements))
    rerank = AsyncMock(side_effect=AssertionError("fit order must be authoritative"))
    monkeypatch.setattr(matching, "rerank_or_passthrough", rerank)
    monkeypatch.setattr(matching.settings, "AI_MATCHES_RERANK_TOP_N", 20)
    rows, reranked = await matching._shared_engine_matches(
        None,
        job=job,
        ordered=candidates,
        similarity_map={1: 0.99, 2: 0.5, 3: 0.99},
        semantic_unknown_ids={1},
        current_user=SimpleNamespace(id=42, get_all_roles=lambda: []),
        required_skills=[],
        nice_skills=[],
        rubric_inputs=None,
        elig_annotations={},
        query_text="truncated",
    )
    expected = await fit.score_pair(
        None,
        build_request_context(job, DEFAULT_PROFILE),
        candidates[-1],
        measurements[1],
    )
    assert [row["candidate"]["id"] for row in rows] == [1, 2, 3]
    assert rows[0]["total_score"] == expected.fit_score
    assert rows[0]["match_score"] == pytest.approx(expected.fit_score / 100, abs=0.0001)
    assert rows[2]["total_score"] is None and rows[2]["match_score"] is None
    assert rows[2]["breakdown"] is None and rows[2]["measurement"] == "stale"
    assert rows[0]["context_fingerprint"] == rows[2]["context_fingerprint"]
    assert "TAIL_C2" in query.call_args.args[0]
    profile.assert_awaited_once_with(None, user_id=42, client_id=8)
    legacy.assert_not_awaited()
    rerank.assert_not_awaited()
    assert reranked is False


@pytest.mark.asyncio
@pytest.mark.parametrize("hits", [[], [{"candidate_id": 1, "score": 0.99}]])
async def test_c2_unknown_measurement_survives_threshold_in_both_discovery_paths(
    monkeypatch, hits
):
    from app.api import matching
    from app.services import retrieval_pool
    from app.services.dealbreaker_filters import DealbreakerInputs

    from app.models.job import Job

    job = Job(id=7, client_id=8, title="Python", location=None)
    candidate = make_candidate(id=1)
    db = AsyncMock()
    db.execute.side_effect = [
        SimpleNamespace(scalar_one_or_none=lambda: job),
        SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [candidate])),
    ]
    monkeypatch.setattr(matching.settings, "AI_MATCHES_SHARED_ENGINE", True)
    monkeypatch.setattr(
        retrieval_pool, "retrieve_candidate_pool", AsyncMock(return_value=hits)
    )
    monkeypatch.setattr(
        matching,
        "_gate_and_dealbreakers",
        AsyncMock(return_value=([candidate], {}, {}, 0, DealbreakerInputs())),
    )
    scorer = AsyncMock(
        return_value=(
            [
                {
                    "candidate": {"id": 1, "location": None},
                    "match_score": None,
                    "total_score": None,
                    "measurement": "missing_index",
                }
            ],
            False,
        )
    )
    monkeypatch.setattr(matching, "_shared_engine_matches", scorer)
    result = await matching.get_ai_matches(
        7,
        current_user=SimpleNamespace(id=42),
        min_score=1.0,
        limit=20,
        location=None,
        db=db,
    )
    assert len(result["matches"]) == 1
    assert result["matches"][0]["match_score"] is None
    assert result["meta"]["degraded"] is True
    scorer.assert_awaited_once()
