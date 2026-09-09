from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services import candidate_search_worker as worker
from app.services.full_candidate_scan import CandidateSnapshot
from app.services.full_search_measurement import VectorMeasurement
from app.services.request_matching_context import build_request_context
from app.services.scoring_service import DEFAULT_PROFILE
from tests.test_scoring_service import make_candidate, make_job


@pytest.mark.asyncio
async def test_shared_batch_preserves_missing_measurement_and_uses_review_policy(
    monkeypatch,
):
    from app.api import matching

    candidate = make_candidate(skills=["Python"], expected_rate_currency="PLN")
    candidate.updated_at = datetime.now(timezone.utc)
    seen = {}

    async def load(_db, _batch):
        return {candidate.id: candidate}

    async def gate(_db, **kwargs):
        seen["must"] = kwargs["inputs"].must_skills
        return [candidate], {}, {}, 0, kwargs["inputs"]

    async def measurements(_vector, _candidates):
        return {candidate.id: VectorMeasurement(None, "missing_index")}

    monkeypatch.setattr(worker, "load_snapshot_batch", load)
    monkeypatch.setattr(matching, "_gate_and_dealbreakers", gate)
    monkeypatch.setattr(worker, "measure_candidates", measurements)
    context = build_request_context(
        make_job(must_skills=["Python", "Django"]), DEFAULT_PROFILE
    )
    result = await worker.evaluate_batch(
        None, context, [CandidateSnapshot(candidate.id, "v1")], [1, 0]
    )
    assert seen["must"] == ()
    assert result[0].eligible and result[0].fit_score is None
    assert result[0].measurement == "missing_index"
    assert [r["status"] for r in result[0].evidence["requirements"]] == [
        "met",
        "unknown",
    ]


@pytest.mark.asyncio
async def test_query_failure_is_checkpointed_and_population_still_accounted(
    monkeypatch,
):
    context = build_request_context(make_job(), DEFAULT_PROFILE)
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = SimpleNamespace(
        request_context=context.as_dict(), metrics={}
    )
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(worker.store, "claim_run", AsyncMock(return_value="lease"))
    checkpoint = AsyncMock()
    save_batch = AsyncMock()
    finish = AsyncMock()
    monkeypatch.setattr(worker.store, "save_metrics", checkpoint)
    monkeypatch.setattr(worker.store, "save_batch", save_batch)
    monkeypatch.setattr(worker.store, "finish_run", finish)
    monkeypatch.setattr(
        worker.store,
        "pending_batch",
        AsyncMock(
            side_effect=[
                [CandidateSnapshot(1, "v1")],
                [],
            ]
        ),
    )
    monkeypatch.setattr(
        worker,
        "request_vector",
        AsyncMock(side_effect=RuntimeError("provider private message")),
    )
    evaluate = AsyncMock(return_value=[])
    monkeypatch.setattr(worker, "evaluate_batch", evaluate)
    await worker.execute_run("run")
    assert checkpoint.await_count == 2
    query_metrics = checkpoint.call_args.args[3]
    assert query_metrics["stages"]["query_embedding"]["failed"] == 1
    assert evaluate.call_args.args[3] is None
    assert save_batch.call_args.kwargs["metrics"]["stages"]["batch"]["calls"] == 1
    assert "provider private message" not in str(save_batch.call_args.kwargs)
    finish.assert_awaited_once()
