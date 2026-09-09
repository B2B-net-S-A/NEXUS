import asyncio
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.config import settings
from app.services.search_telemetry import (
    SearchTelemetry,
    record_embedding_attempt,
    stage,
)


def record(tokens=100, failed=False, model="test-model"):
    record_embedding_attempt(model=model, tokens=tokens, failed=failed, elapsed_ms=10)


def test_unknown_usage_and_unpriced_models_never_claim_zero_total(monkeypatch):
    monkeypatch.setattr(settings, "AI_SEARCH_EMBEDDING_PRICES", {"test-model": 2.0})
    meter = SearchTelemetry()
    meter.begin_attempt()
    with meter.activate(), stage("query_embedding"):
        record(1000)
        record(None, failed=True)
        record(10, model="unpriced")
    result = meter.snapshot()
    assert result["known_cost_usd"] == 0.002
    assert result["estimated_cost_usd"] is None
    assert not result["cost_complete"]
    assert sum(p["calls"] for p in result["providers"].values()) == 3
    assert sum(p["observed_tokens"] for p in result["providers"].values()) == 1010
    assert result["stages"]["generation"]["calls"] == 0
    assert result["stages"]["rerank"]["calls"] == 0


def test_resumption_preserves_checkpoints_but_marks_possible_lost_accounting(
    monkeypatch,
):
    monkeypatch.setattr(settings, "AI_SEARCH_EMBEDDING_PRICES", {"test-model": 2.0})
    meter = SearchTelemetry()
    meter.begin_attempt()
    with meter.activate():
        record(1000)
    checkpoint = meter.snapshot()
    assert checkpoint["estimated_cost_usd"] == 0.002
    resumed = SearchTelemetry(checkpoint)
    resumed.begin_attempt()
    with resumed.activate():
        record(500)
    result = resumed.snapshot()
    assert result["attempts"] == 2 and not result["accounting_complete"]
    assert result["known_cost_usd"] == 0.003
    assert result["estimated_cost_usd"] is None
    assert checkpoint["known_cost_usd"] == 0.002  # no mutation of stored JSON


def test_histogram_is_bounded_and_p95_is_explicit_upper_bound():
    meter = SearchTelemetry()
    for _ in range(95):
        meter.duration("batch", 101, False)
    for _ in range(5):
        meter.duration("batch", 200001, True)
    result = meter.snapshot()["stages"]["batch"]
    assert result["p95_upper_bound_ms"] == 250
    assert result["calls"] == 100 and result["failed"] == 5
    assert len(result["histogram"]) == 16


@pytest.mark.asyncio
async def test_concurrent_runs_do_not_mix_provider_usage(monkeypatch):
    monkeypatch.setattr(settings, "AI_SEARCH_EMBEDDING_PRICES", {})

    async def collect(tokens):
        meter = SearchTelemetry()
        with meter.activate(), stage("query_embedding"):
            await asyncio.sleep(0)
            record(tokens)
        return meter.snapshot()

    results = await asyncio.gather(collect(111), collect(222))
    assert [
        sum(p["observed_tokens"] for p in r["providers"].values()) for r in results
    ] == [111, 222]


@pytest.mark.asyncio
async def test_real_embedding_gateway_records_each_retry_and_usage(monkeypatch):
    from app.services import embedding_service as embeddings

    monkeypatch.setattr(settings, "VOYAGE_API_KEY", "test-not-a-real-key")
    monkeypatch.setattr(settings, "AI_SEARCH_EMBEDDING_PRICES", {"test-model": 2.0})
    monkeypatch.setattr(embeddings, "_voyage_model", lambda: "test-model")
    monkeypatch.setattr(embeddings, "_VOYAGE_RETRY_BACKOFF_SECONDS", 0)
    request = httpx.Request("POST", "https://example.invalid/embeddings")
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.post.side_effect = [
        httpx.Response(429, request=request),
        httpx.Response(
            200,
            request=request,
            json={
                "data": [{"index": 0, "embedding": [1, 0]}],
                "usage": {"total_tokens": 123},
            },
        ),
    ]
    monkeypatch.setattr(embeddings.httpx, "AsyncClient", lambda **kwargs: client)
    meter = SearchTelemetry()
    with meter.activate(), stage("query_embedding"):
        assert await embeddings._voyage_embed_batch(["test"]) == [[1, 0]]
    value = next(iter(meter.snapshot()["providers"].values()))
    assert value["calls"] == 2 and value["failed"] == 1
    assert value["observed_tokens"] == 123
    assert value["usage_unknown_calls"] == 1
    assert value["known_cost_usd"] == pytest.approx(0.000246)


def test_failed_stage_is_recorded_and_context_is_reset():
    meter = SearchTelemetry()
    with pytest.raises(RuntimeError), meter.activate(), stage("retrieval"):
        raise RuntimeError("private provider detail")
    record(123)
    result = meter.snapshot()
    assert result["stages"]["retrieval"]["failed"] == 1
    assert result["providers"] == {}
    assert "private provider detail" not in str(result)


def test_run_report_keeps_partial_runs_in_latency_and_unknown_cost_out_of_mean():
    from scripts.report_candidate_search_metrics import summarize_runs

    rows = [
        (
            "complete",
            {
                "elapsed_ms": i * 100,
                "estimated_cost_usd": 0.02,
                "known_cost_usd": 0.02,
                "cost_complete": True,
            },
        )
        for i in range(1, 20)
    ]
    rows.append(
        (
            "partial",
            {"elapsed_ms": 99999, "known_cost_usd": 0.01, "cost_complete": False},
        )
    )
    rows.append(("partial", {}))  # legacy run has no measurement
    result = summarize_runs(rows)
    assert result["elapsed_p95_ms"] == 1900
    assert result["partial_runs"] == 2
    assert result["latency_samples"] == 20 and result["latency_unknown_runs"] == 1
    assert result["fully_priced_runs"] == 19 and result["cost_unknown_runs"] == 2
    assert result["mean_estimated_cost_usd_for_priced_runs"] == pytest.approx(0.02)
    assert result["known_cost_subtotal_usd"] == pytest.approx(0.39)
    assert result["estimated_total_cost_usd"] is None
    assert summarize_runs([])["elapsed_p95_ms"] is None
