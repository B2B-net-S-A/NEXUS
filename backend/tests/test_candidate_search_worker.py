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
        seen["unknown"] = kwargs["inputs"].exclude_unknown_skill_evidence
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
    # Decision 10.09: under the default "review" policy the gate keeps the
    # technology must-haves (a KNOWN gap hides) but lets missing proof pass.
    from app.services.scoring_service import canonical_skill_names

    assert seen["must"] == tuple(canonical_skill_names(["Python", "Django"]))
    assert seen["unknown"] is False
    assert result[0].eligible and result[0].fit_score is None
    assert result[0].measurement == "missing_index"
    assert [r["status"] for r in result[0].evidence["requirements"]] == [
        "met",
        "unknown",
    ]


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_failure", [False, True])
async def test_query_failure_is_checkpointed_and_population_still_accounted(
    monkeypatch,
    batch_failure,
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
    evaluate = AsyncMock(
        side_effect=RuntimeError("Incomplete candidate eligibility assessment")
        if batch_failure
        else None,
        return_value=[],
    )
    monkeypatch.setattr(worker, "evaluate_batch", evaluate)
    await worker.execute_run("run")
    assert checkpoint.await_count == 2
    query_metrics = checkpoint.call_args.args[3]
    assert query_metrics["stages"]["query_embedding"]["failed"] == 1
    assert evaluate.call_args.args[3] is None
    assert save_batch.call_args.kwargs["metrics"]["stages"]["batch"]["calls"] == 1
    assert "provider private message" not in str(save_batch.call_args.kwargs)
    if batch_failure:
        assert save_batch.call_args.args[4] == []
        assert save_batch.call_args.kwargs["error_code"] == "RuntimeError"
        assert save_batch.call_args.kwargs["metrics"]["stages"]["batch"]["failed"] == 1
    finish.assert_awaited_once()


def _wire_lifecycle(monkeypatch, *, claims, fail_with):
    """Worker whose first checkpoint raises; returns the lifecycle mocks."""
    context = build_request_context(make_job(), DEFAULT_PROFILE)
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = SimpleNamespace(
        request_context=context.as_dict(), metrics={"claims": claims}
    )
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(worker.store, "claim_run", AsyncMock(return_value="lease"))
    monkeypatch.setattr(worker.store, "save_metrics", AsyncMock(side_effect=fail_with))
    fail, release = AsyncMock(return_value=True), AsyncMock(return_value=True)
    monkeypatch.setattr(worker.store, "fail_run", fail)
    monkeypatch.setattr(worker.store, "release_run", release)
    vector = AsyncMock(return_value=[1, 0])
    monkeypatch.setattr(worker, "request_vector", vector)
    return fail, release, vector


@pytest.mark.asyncio
@pytest.mark.parametrize("claims,terminal", [(1, False), (2, False), (3, True)])
async def test_non_transient_failure_is_retried_then_becomes_terminal(
    monkeypatch, claims, terminal
):
    fail, release, _ = _wire_lifecycle(
        monkeypatch, claims=claims, fail_with=ValueError("unaccounted population")
    )
    await worker.execute_run("run")
    if terminal:
        # Code only — never the exception text, which may carry private data.
        fail.assert_awaited_once()
        assert fail.call_args.args[1:] == ("run", "ValueError")
        assert fail.call_args.kwargs == {"token": "lease"}
        release.assert_not_awaited()
    else:
        # A fresh claim follows at once; the durable counter bounds it.
        release.assert_awaited_once()
        assert release.call_args.args[1:] == ("run", "lease")
        fail.assert_not_awaited()


@pytest.mark.asyncio
async def test_claim_beyond_budget_fails_before_any_provider_work(monkeypatch):
    fail, release, vector = _wire_lifecycle(
        monkeypatch, claims=worker.MAX_CLAIMS + 1, fail_with=None
    )
    await worker.execute_run("run")
    fail.assert_awaited_once()
    assert fail.call_args.args[1:] == ("run", "attempts_exhausted")
    vector.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_unreported_claims_from_deploys_do_not_exhaust_a_healthy_run(
    monkeypatch,
):
    """Coolify restartuje kontener przy każdym pushu na main — przejęcia bez
    raportu (proces zabity w trakcie) nie mogą kończyć zdrowego przeglądu po
    trzech deployach (przegląd adwersarialny 10.09)."""
    fail, _release, vector = _wire_lifecycle(monkeypatch, claims=5, fail_with=None)
    await worker.execute_run("run")
    vector.assert_awaited()
    assert all(
        call.args[2:3] != ("attempts_exhausted",) for call in fail.await_args_list
    )


@pytest.mark.asyncio
async def test_lost_lease_is_not_recorded_by_the_stale_worker(monkeypatch):
    fail, release, _ = _wire_lifecycle(
        monkeypatch, claims=3, fail_with=worker.store.SearchLeaseLost("replaced")
    )
    await worker.execute_run("run")
    fail.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_transient_database_error_waits_for_lease_expiry(monkeypatch):
    from sqlalchemy.exc import OperationalError

    error = OperationalError("SELECT 1", {}, ConnectionError("connection reset"))
    fail, release, _ = _wire_lifecycle(monkeypatch, claims=3, fail_with=error)
    with pytest.raises(OperationalError):
        await worker.execute_run("run")
    fail.assert_not_awaited()
    release.assert_not_awaited()


@pytest.mark.asyncio
async def test_stalled_runs_are_reaped_before_the_next_run_is_picked(monkeypatch):
    import asyncio

    from app.tasks import candidate_search_worker as loop

    calls = []
    session = AsyncMock()
    session.__aenter__.return_value = session

    async def reap(db, *, stalled_after):
        calls.append(("reap", stalled_after))
        return ["stalled-run"]

    async def pick(*_args, **_kwargs):
        calls.append("pick")
        raise asyncio.CancelledError  # stop the endless loop after one tick

    session.scalar.side_effect = pick
    monkeypatch.setattr(loop, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(loop.store, "reap_stalled_runs", reap)
    with pytest.raises(asyncio.CancelledError):
        await loop.candidate_search_loop()
    assert calls == [("reap", loop.STALLED_AFTER), "pick"]
    session.commit.assert_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_stage", ["query", "batch"])
async def test_timeout_cancels_slow_work_and_checkpoints_incomplete_result(
    monkeypatch, slow_stage
):
    import asyncio

    context = build_request_context(make_job(), DEFAULT_PROFILE)
    session = AsyncMock()
    session.__aenter__.return_value = session
    session.get.return_value = SimpleNamespace(
        request_context=context.as_dict(), metrics={}
    )
    monkeypatch.setattr(worker, "AsyncSessionLocal", lambda: session)
    monkeypatch.setattr(worker.store, "claim_run", AsyncMock(return_value="lease"))
    checkpoint, save, finish = AsyncMock(), AsyncMock(), AsyncMock()
    monkeypatch.setattr(worker.store, "save_metrics", checkpoint)
    monkeypatch.setattr(worker.store, "save_batch", save)
    monkeypatch.setattr(worker.store, "finish_run", finish)
    monkeypatch.setattr(
        worker.store,
        "pending_batch",
        AsyncMock(side_effect=[[CandidateSnapshot(1, "v1")], []]),
    )
    cancelled = asyncio.Event()

    async def slow(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    monkeypatch.setattr(worker, "QUERY_TIMEOUT_SECONDS", 0.01)
    monkeypatch.setattr(worker, "BATCH_TIMEOUT_SECONDS", 0.01)
    query = AsyncMock(
        side_effect=slow if slow_stage == "query" else None, return_value=[1, 0]
    )
    evaluate = AsyncMock(
        side_effect=slow if slow_stage == "batch" else None, return_value=[]
    )
    monkeypatch.setattr(worker, "request_vector", query)
    monkeypatch.setattr(worker, "evaluate_batch", evaluate)
    await worker.execute_run("run")
    assert cancelled.is_set()
    query.assert_awaited_once()
    evaluate.assert_awaited_once()
    finish.assert_awaited_once()
    if slow_stage == "query":
        assert evaluate.call_args.args[3] is None
        assert checkpoint.call_args.args[3]["stages"]["query_embedding"]["failed"] == 1
    else:
        session.rollback.assert_awaited_once()
        assert save.call_args.args[4] == []
        assert save.call_args.kwargs["error_code"] == "TimeoutError"
        assert save.call_args.kwargs["metrics"]["stages"]["batch"]["failed"] == 1
