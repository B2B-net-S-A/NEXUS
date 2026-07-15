"""Deterministic unit tests for the offline matching evaluator (plan PR1).

These cover the pure, DB-free surface of ``scripts/eval_matching.py``:
  * the ranking metrics maths (``_metrics``);
  * that every ablation profile is a valid six-layer budget summing to 100;
  * that the eval profile maps cleanly onto the engine's ``WeightProfile``
    (so ablation weights actually reach scoring instead of the old no-op
    monkeypatch).

The end-to-end evaluator needs a live DB + Qdrant + Voyage and is exercised
separately; it is intentionally not imported here.
"""

from __future__ import annotations

import math

import pytest

from app.services import scoring_service
from scripts.eval_matching import (
    ABLATION_PROFILES,
    DEFAULT_PROFILE,
    WeightProfile,
    _metrics,
    _to_scoring_profile,
)


def test_default_profile_matches_engine_budget():
    """Eval default must mirror the live engine (35/30/12/8/5/10 = 100)."""
    engine = scoring_service.WeightProfile()  # built-in default
    assert DEFAULT_PROFILE.semantic == engine.semantic
    assert DEFAULT_PROFILE.skills == engine.skills
    assert DEFAULT_PROFILE.salary == engine.salary
    assert DEFAULT_PROFILE.location == engine.location
    assert DEFAULT_PROFILE.availability == engine.availability
    assert DEFAULT_PROFILE.champion_fit == engine.champion_fit
    assert DEFAULT_PROFILE.budget == pytest.approx(100.0)


@pytest.mark.parametrize("profile", ABLATION_PROFILES, ids=lambda p: p.name)
def test_ablation_profiles_sum_to_100(profile: WeightProfile):
    assert profile.budget == pytest.approx(100.0), (
        f"{profile.name} budget={profile.budget}"
    )


def test_to_scoring_profile_preserves_all_layers():
    ev = WeightProfile(
        name="custom",
        semantic=10.0,
        skills=20.0,
        salary=30.0,
        location=15.0,
        availability=5.0,
        champion_fit=20.0,
    )
    sp = _to_scoring_profile(ev)
    assert isinstance(sp, scoring_service.WeightProfile)
    assert (sp.semantic, sp.skills, sp.salary) == (10.0, 20.0, 30.0)
    assert (sp.location, sp.availability, sp.champion_fit) == (15.0, 5.0, 20.0)
    assert sp.name == "custom"


def test_metrics_perfect_ranking():
    # GT = {1,2,3}; ranked perfectly first.
    relevance = {1: 2.0, 2: 1.0, 3: 0.5}
    ranked = [1, 2, 3, 4, 5, 6]
    p5, r20, mrr, ndcg = _metrics(ranked, relevance)
    assert p5 == pytest.approx(3 / 5)  # 3 of top-5 are relevant
    assert r20 == pytest.approx(1.0)  # all 3 GT within top-20
    assert mrr == pytest.approx(1.0)  # first hit at rank 1
    assert ndcg == pytest.approx(1.0)  # ideal order


def test_metrics_no_hits():
    relevance = {10: 1.0}
    ranked = [1, 2, 3]
    p5, r20, mrr, ndcg = _metrics(ranked, relevance)
    assert (p5, r20, mrr, ndcg) == (0.0, 0.0, 0.0, 0.0)


def test_metrics_empty_ground_truth_is_zero():
    assert _metrics([1, 2, 3], {}) == (0.0, 0.0, 0.0, 0.0)


def test_metrics_mrr_uses_first_relevant_rank():
    relevance = {7: 1.0}
    ranked = [1, 2, 7, 8]  # first hit at rank 3
    _, _, mrr, _ = _metrics(ranked, relevance)
    assert mrr == pytest.approx(1 / 3)


def test_metrics_ndcg_rewards_better_order():
    relevance = {1: 3.0, 2: 1.0}
    good = _metrics([1, 2, 9], relevance)[3]
    bad = _metrics([2, 1, 9], relevance)[3]
    assert good > bad
    assert good == pytest.approx(1.0)
    # Sanity: bad order still positive but strictly worse.
    assert 0.0 < bad < 1.0
    assert not math.isnan(bad)
