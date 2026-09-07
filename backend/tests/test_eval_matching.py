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

from app.models.recruitment_pipeline import PipelineStage
from app.services import scoring_service
from scripts.eval_matching import (
    ABLATION_PROFILES,
    DEFAULT_PROFILE,
    POSITIVE_STAGES,
    STAGE_RELEVANCE,
    JobEval,
    ProfileEval,
    WeightProfile,
    _apply_structured_pool_args,
    _metrics,
    _parse_args,
    _to_scoring_profile,
    recall_ceiling_at_20,
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
    p5, r20, r20n, mrr, ndcg = _metrics(ranked, relevance)
    assert p5 == pytest.approx(3 / 5)  # 3 of top-5 are relevant
    assert r20 == pytest.approx(1.0)  # all 3 GT within top-20
    assert r20n == pytest.approx(1.0)  # ceiling is 1.0 for |GT| <= 20
    assert mrr == pytest.approx(1.0)  # first hit at rank 1
    assert ndcg == pytest.approx(1.0)  # ideal order


def test_metrics_no_hits():
    relevance = {10: 1.0}
    ranked = [1, 2, 3]
    assert _metrics(ranked, relevance) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_metrics_empty_ground_truth_is_zero():
    assert _metrics([1, 2, 3], {}) == (0.0, 0.0, 0.0, 0.0, 0.0)


def test_metrics_mrr_uses_first_relevant_rank():
    relevance = {7: 1.0}
    ranked = [1, 2, 7, 8]  # first hit at rank 3
    mrr = _metrics(ranked, relevance)[3]
    assert mrr == pytest.approx(1 / 3)


def test_metrics_ndcg_rewards_better_order():
    relevance = {1: 3.0, 2: 1.0}
    good = _metrics([1, 2, 9], relevance)[4]
    bad = _metrics([2, 1, 9], relevance)[4]
    assert good > bad
    assert good == pytest.approx(1.0)
    # Sanity: bad order still positive but strictly worse.
    assert 0.0 < bad < 1.0
    assert not math.isnan(bad)


# ── Recall normalization (Recall@20 vs ground-truth size) ────────────────────


@pytest.mark.parametrize(
    "gt_size,expected",
    [
        (0, 0.0),
        (1, 1.0),
        (20, 1.0),  # exactly fits
        (40, 0.5),
        (61, pytest.approx(20 / 61)),  # a real shape on prod
        (197, pytest.approx(20 / 197)),  # the observed maximum
    ],
)
def test_recall_ceiling_tracks_ground_truth_size(gt_size, expected):
    assert recall_ceiling_at_20(gt_size) == expected


def test_normalized_recall_is_one_for_a_perfect_ranker_on_oversized_gt():
    """A ranker that fills all 20 slots with ground truth has done everything
    possible — even when |GT| is 61 and raw Recall@20 therefore reads 0.33.

    This is the whole point of normalizing: without it, 18.3% of prod jobs
    (those with |GT| > 20) drag the mean down for a reason no ranking change
    can fix, and the engine looks broken when it is saturated.
    """
    relevance = {i: 1.0 for i in range(61)}
    ranked = list(range(61))  # perfect order
    _, r20, r20n, _, _ = _metrics(ranked, relevance)
    assert r20 == pytest.approx(20 / 61)
    assert r20n == pytest.approx(1.0)


def test_normalized_recall_makes_two_jobs_comparable():
    """Same ranker quality (half the reachable ground truth found) on two very
    different |GT| sizes must produce the same normalized score."""
    small_rel = {i: 1.0 for i in range(10)}
    small_ranked = list(range(5)) + list(range(100, 115))  # 5 of 10 in top-20

    big_rel = {i: 1.0 for i in range(40)}
    big_ranked = list(range(10)) + list(range(100, 110))  # 10 of 20 slots

    _, small_raw, small_norm, _, _ = _metrics(small_ranked, small_rel)
    _, big_raw, big_norm, _, _ = _metrics(big_ranked, big_rel)

    assert small_raw != pytest.approx(big_raw)  # raw figures disagree...
    assert small_norm == pytest.approx(0.5)
    assert big_norm == pytest.approx(0.5)  # ...normalized ones agree


# ── Ground-truth relevance map ───────────────────────────────────────────────


def test_verified_stage_counts_as_ground_truth():
    """`verified` is the rate-acceptance gate — a recruiter-vetted candidate.

    It was missing from the map, which silently dropped 658 (candidate, job)
    pairs whose only positive row is `verified` (measured on prod 2026-08-07).
    """
    assert PipelineStage.verified in STAGE_RELEVANCE
    assert STAGE_RELEVANCE[PipelineStage.verified] > 0
    assert PipelineStage.verified in POSITIVE_STAGES


@pytest.mark.parametrize(
    "stage",
    [
        PipelineStage.new,
        PipelineStage.prep_call,
        PipelineStage.rejected,
        PipelineStage.withdrawn,
    ],
)
def test_non_signal_stages_stay_out_of_ground_truth(stage):
    """Guard the guard: widening the map must not quietly admit negatives.

    `rejected`/`withdrawn` are negative signal and `new`/`prep_call` carry none;
    counting any of them as ground truth would reward the engine for surfacing
    people the recruiter already turned down.
    """
    assert stage not in STAGE_RELEVANCE
    assert stage not in POSITIVE_STAGES


# ── Index-coverage bookkeeping ───────────────────────────────────────────────


def _job_eval(job_id: int, gt_size: int, indexed):
    return JobEval(
        job_id=job_id,
        job_title=f"Job {job_id}",
        ground_truth_ids=list(range(gt_size)),
        ranked_candidate_ids=[],
        relevance_map={},
        precision_at_5=0.4,
        recall_at_20=0.5,
        recall_at_20_normalized=0.5,
        mrr=0.5,
        ndcg_at_10=0.5,
        pool_size=200,
        ground_truth_indexed=indexed,
    )


def test_unknown_index_coverage_is_not_treated_as_fully_indexed():
    """`None` means Qdrant could not answer — an unanswered question is not a
    passing answer, so the job must stay out of the verdict-grade subset.

    Without this, a Qdrant blip during the run would quietly promote every job
    into "fully indexed" and the headline metric would be computed over data
    nobody verified.
    """
    ev = ProfileEval(profile=DEFAULT_PROFILE)
    ev.per_job = [_job_eval(1, gt_size=5, indexed=None)]
    assert ev.fully_indexed_jobs == []


def test_zero_indexed_is_a_real_answer_and_also_excluded():
    """0 is distinct from None but likewise not fully indexed."""
    ev = ProfileEval(profile=DEFAULT_PROFILE)
    ev.per_job = [_job_eval(1, gt_size=5, indexed=0)]
    assert ev.fully_indexed_jobs == []


def test_fully_indexed_subset_drives_the_headline_metrics():
    ev = ProfileEval(profile=DEFAULT_PROFILE)
    ev.per_job = [
        _job_eval(1, gt_size=5, indexed=5),  # complete
        _job_eval(2, gt_size=5, indexed=2),  # partial — data hole, not ranking
        _job_eval(3, gt_size=5, indexed=None),  # unknown
    ]
    assert [j.job_id for j in ev.fully_indexed_jobs] == [1]
    # Mean over the whole set still exists, but the verdict-grade one is the
    # restricted variant.
    assert ev.mean_precision_at_5 == pytest.approx(0.4)
    assert ev.mean_precision_at_5_fully_indexed == pytest.approx(0.4)


def test_relevance_is_monotonic_along_the_funnel():
    """Later funnel stages must never score below earlier ones.

    Lists ALL nine GT-contributing stages, not a subset: a partial list would
    let a mis-scored stage (say `interview` above `client_interview`) sit
    outside the assertion and never be checked — a guard that guards part of
    the thing it names.
    """
    funnel = [
        PipelineStage.screening,
        PipelineStage.verified,
        PipelineStage.interview,
        PipelineStage.cv_sent,
        PipelineStage.client_interview,
        PipelineStage.acceptance,
        PipelineStage.negotiation,
        PipelineStage.onboarding,
        PipelineStage.hired,
    ]
    assert set(funnel) == set(STAGE_RELEVANCE), (
        "the funnel list and STAGE_RELEVANCE have drifted apart — every graded "
        f"stage must appear here. Missing: {set(STAGE_RELEVANCE) - set(funnel)}; "
        f"unexpected: {set(funnel) - set(STAGE_RELEVANCE)}"
    )
    scores = [STAGE_RELEVANCE[s] for s in funnel]
    assert scores == sorted(scores), f"funnel relevance not monotonic: {scores}"


# ── 0278: --structured-pool must actually reach `settings` ──────────────────
#
# `_apply_structured_pool_args` is the pure, DB-free slice of `_run` that
# applies these two CLI flags — extracted specifically so this is testable
# without a live Postgres/Qdrant/Voyage (the rest of `_run` needs all three;
# see the module docstring above).


def test_structured_pool_arg_sets_the_setting(monkeypatch):
    """Without this, `--structured-pool` is cosmetic: the harness would keep
    measuring the OLD pool regardless of the flag, and an A/B comparing "on"
    vs "off" would silently compare the same run against itself."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "STRUCTURED_POOL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "STRUCTURED_POOL_LIMIT", 2000, raising=False)

    args = _parse_args(["--structured-pool", "--structured-pool-limit", "500"])
    assert args.structured_pool is True
    assert args.structured_pool_limit == 500

    _apply_structured_pool_args(args)

    assert settings.STRUCTURED_POOL_ENABLED is True
    assert settings.STRUCTURED_POOL_LIMIT == 500


def test_structured_pool_arg_off_leaves_settings_at_their_defaults(monkeypatch):
    """A run without `--structured-pool` must reproduce today's pool exactly —
    a bare invocation flipping a global as a side effect would be the kind of
    bug an A/B run is supposed to catch, not cause."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "STRUCTURED_POOL_ENABLED", False, raising=False)
    monkeypatch.setattr(settings, "STRUCTURED_POOL_LIMIT", 2000, raising=False)

    args = _parse_args([])
    assert args.structured_pool is False
    assert args.structured_pool_limit is None

    _apply_structured_pool_args(args)

    assert settings.STRUCTURED_POOL_ENABLED is False
    assert settings.STRUCTURED_POOL_LIMIT == 2000
