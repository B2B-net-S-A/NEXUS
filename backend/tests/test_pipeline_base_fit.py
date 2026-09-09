from unittest.mock import AsyncMock

import pytest

from app.services import pipeline_base_fit as pipeline
from app.services.full_candidate_scan import CandidateEvaluation, CandidateSnapshot
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
async def test_all_pipeline_members_are_visited_even_without_scores(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = [(i, "version") for i in range(1, 602)]
    seen = []
    query = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(pipeline, "request_vector", query)

    async def evaluate(_db, context, batch, vector):
        seen.extend(item.candidate_id for item in batch)
        assert len(batch) <= 256
        return [
            CandidateEvaluation(
                item.candidate_id,
                item.version,
                True,
                None if item.candidate_id == 601 else 78.6,
                "missing_index" if item.candidate_id == 601 else "measured",
            )
            for item in batch
        ]

    monkeypatch.setattr(pipeline, "evaluate_batch", evaluate)
    result = await pipeline.pipeline_base_fit(db, make_job(), DEFAULT_PROFILE)
    assert seen == result["pipeline_candidate_ids"] == list(range(1, 602))
    assert len(result["scores"]) == 600 and result["scores"]["1"] == 78.6
    assert "601" not in result["scores"]
    assert result["counts"]["needs_verification"] == 1
    query.assert_awaited_once()
    assert "LIMIT" not in str(db.execute.call_args.args[0])


@pytest.mark.asyncio
async def test_pipeline_and_full_search_use_identical_actual_base_fit(monkeypatch):
    from app.api import matching
    from app.services import candidate_search_worker as worker
    from app.services.full_search_measurement import VectorMeasurement

    candidate = make_candidate(id=7, skills=["Python", "Django"], updated_at="v1")
    job = make_job(
        description="Background. " * 1200 + "Required: Django", must_skills=["Python"]
    )
    context = build_request_context(job, DEFAULT_PROFILE)
    monkeypatch.setattr(
        worker, "load_snapshot_batch", AsyncMock(return_value={7: candidate})
    )
    monkeypatch.setattr(
        matching,
        "_gate_and_dealbreakers",
        AsyncMock(return_value=([candidate], {}, {}, 0, None)),
    )
    monkeypatch.setattr(
        worker,
        "measure_candidates",
        AsyncMock(return_value={7: VectorMeasurement(0.8, "measured")}),
    )
    query = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(pipeline, "request_vector", query)
    db = AsyncMock()
    db.execute.return_value = [(7, "v1")]
    full = await worker.evaluate_batch(
        db, context, [CandidateSnapshot(7, "v1")], [1, 0]
    )
    cards = await pipeline.pipeline_base_fit(db, job, DEFAULT_PROFILE)
    assert cards["scores"]["7"] == full[0].fit_score
    assert cards["request_fingerprint"] == context.fingerprint
    assert query.call_args.args[0] == context.query_text
    assert "Required: Django" in query.call_args.args[0]


@pytest.mark.asyncio
async def test_failed_batch_does_not_drop_membership_or_fabricate_zero(monkeypatch):
    db = AsyncMock()
    db.execute.return_value = [(i, "v1") for i in range(1, 258)]
    monkeypatch.setattr(pipeline, "request_vector", AsyncMock(return_value=None))

    async def evaluate(_db, _context, batch, _vector):
        if batch[0].candidate_id == 1:
            raise RuntimeError("private text")
        return [CandidateEvaluation(257, "v1", True, None, "unavailable")]

    monkeypatch.setattr(pipeline, "evaluate_batch", evaluate)
    result = await pipeline.pipeline_base_fit(db, make_job(), DEFAULT_PROFILE)
    assert len(result["pipeline_candidate_ids"]) == 257
    assert result["scores"] == {}
    assert result["counts"]["failed"] == 256
    assert result["counts"]["evaluated"] == 1
    assert not result["counts"]["coverage_complete"]
    assert "private text" not in str(result)
    db.rollback.assert_awaited_once()
