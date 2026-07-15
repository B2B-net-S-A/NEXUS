"""Tests for the unified retrieval orchestrator (plan PR8).

Pure fusion/overfetch/gating plus end-to-end run assembly with injected fakes
(no Voyage/Qdrant/DB; telemetry disabled).
"""

from __future__ import annotations

import pytest

from app.core.config import settings
from app.services import matching_orchestrator as orch
from app.services.matching_contracts import MatchingRequest


def test_rrf_boosts_agreed_candidates():
    fused = orch.reciprocal_rank_fusion({"dense": [1, 2, 3], "sparse": [3, 1, 4]})
    ids = [cid for cid, _, _ in fused]
    # 1 and 3 appear in both lists near the top → they lead.
    assert set(ids[:2]) == {1, 3}
    # A candidate seen by two sources records both.
    srcs = {cid: s for cid, _, s in fused}
    assert set(srcs[1]) == {"dense", "sparse"}
    assert srcs[4] == ["sparse"]


def test_rrf_is_deterministic_on_ties():
    a = orch.reciprocal_rank_fusion({"x": [5, 6], "y": [6, 5]})
    b = orch.reciprocal_rank_fusion({"x": [5, 6], "y": [6, 5]})
    assert a == b  # tie-break by candidate_id keeps it stable


def test_adaptive_overfetch():
    assert orch.adaptive_overfetch(20, 1.0) == 20
    assert orch.adaptive_overfetch(20, 0.5) == 40
    assert orch.adaptive_overfetch(20, 0.25) == 80
    # Pathologically low ratio is capped.
    assert orch.adaptive_overfetch(20, 0.0001, cap=500) == 500


def test_surface_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AI_UNIFIED_RETRIEVAL_ENABLED", False)
    assert orch.surface_enabled("recommendations") is False

    monkeypatch.setattr(settings, "AI_UNIFIED_RETRIEVAL_ENABLED", True)
    monkeypatch.setattr(settings, "AI_UNIFIED_RETRIEVAL_SURFACES", "")
    assert orch.surface_enabled("anything") is True  # empty list = all

    monkeypatch.setattr(settings, "AI_UNIFIED_RETRIEVAL_SURFACES", "marketplace")
    assert orch.surface_enabled("marketplace") is True
    assert orch.surface_enabled("recommendations") is False


@pytest.mark.asyncio
async def test_run_matching_orders_and_ranks():
    async def dense():
        return [(1, 0.9), (2, 0.8), (3, 0.7)]

    async def elig(ids):
        return {1: (True, []), 2: (False, ["conflict"]), 3: (True, [])}

    async def score(ids):
        return {i: (50.0 + i, {"semantic": i}) for i in ids}

    run = await orch.run_matching(
        MatchingRequest(surface="test", top_k=10),
        db=None,
        dense_fn=dense,
        eligibility_fn=elig,
        score_fn=score,
        emit_telemetry=False,
    )

    ids = [r.candidate_id for r in run.results]
    # Eligible, higher fit first: 3 (53) then 1 (51); ineligible 2 last.
    assert ids == [3, 1, 2]
    assert [r.rank for r in run.results] == [0, 1, 2]
    assert run.results[-1].eligible is False
    assert run.results[-1].eligibility_reasons == ["conflict"]
    assert run.results[0].fit_score == 53.0
    # Version trace is always populated.
    assert run.version_trace.ranker_version
    assert run.version_trace.text_schema_version


@pytest.mark.asyncio
async def test_run_matching_top_k_truncates():
    async def dense():
        return [(i, 1.0 - i / 100) for i in range(1, 11)]

    async def elig(ids):
        return {i: (True, []) for i in ids}

    async def score(ids):
        return {i: (float(100 - i), {}) for i in ids}

    run = await orch.run_matching(
        MatchingRequest(surface="test", top_k=3),
        db=None,
        dense_fn=dense,
        eligibility_fn=elig,
        score_fn=score,
        emit_telemetry=False,
    )
    assert len(run.results) == 3
    assert [r.candidate_id for r in run.results] == [1, 2, 3]  # best fit first


@pytest.mark.asyncio
async def test_run_matching_degrades_when_dense_fails():
    async def dense():
        raise RuntimeError("qdrant down")

    async def elig(ids):
        return {}

    async def score(ids):
        return {}

    run = await orch.run_matching(
        MatchingRequest(surface="test"),
        db=None,
        dense_fn=dense,
        eligibility_fn=elig,
        score_fn=score,
        emit_telemetry=False,
    )
    assert run.degraded is True
    assert run.results == []
