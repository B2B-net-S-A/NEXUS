"""Guards for the two changes that lift the measured retrieval ceiling.

Baseline 2026-08-10 (40 jobs, 960 ground-truth positives): the scoring layer
never saw 86.4% of ground truth, because the pool handed to it was capped at
200. The ceiling is 1.8% at pool 20, 13.6% at 200, 22.8% at 500, 32.6% at 1000 —
so it is set by retrieval size, not by weights.
"""

from __future__ import annotations

import ast
from pathlib import Path

from app.core.config import settings

BACKEND = Path(__file__).resolve().parents[1]


def test_pool_size_is_configurable_and_distinct_from_result_cap():
    """`MATCH_MAX_RESULTS` caps the RESPONSE; it is not the pool.

    Four call-sites already use it for payload size (`compute_proposals`,
    `matching`, `jobs`, `proposals`), so reusing it for retrieval would silently
    change how much data those return.
    """
    assert settings.MATCH_POOL_SIZE >= 500, (
        "pool below 500 keeps the recall ceiling under ~23% by construction"
    )
    assert settings.MATCH_MAX_RESULTS == 200, (
        "result cap must stay put — it is a different knob from the pool"
    )


def test_pool_size_does_not_depend_on_top_k():
    """The old `min(top_k * 4, 200)` tied retrieval to how many rows we display.

    A request for the top 20 then retrieved 80 and capped its own ceiling at
    ~4%, invisibly.
    """
    for rel in ("app/api/recommendations.py", "app/tasks/compute_proposals.py"):
        src = (BACKEND / rel).read_text(encoding="utf-8")
        assert "min(top_k * 4" not in src, f"{rel} still ties pool size to top_k"
        assert "settings.MATCH_POOL_SIZE" in src, f"{rel} does not read the pool knob"


def _calls_in(module_rel: str, func_name: str) -> set[str]:
    tree = ast.parse((BACKEND / module_rel).read_text(encoding="utf-8"))
    target = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == func_name
        ),
        None,
    )
    assert target is not None, f"{func_name} not found in {module_rel}"
    return {
        n.func.id
        for n in ast.walk(target)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
    }


def test_pool_scoring_builds_the_batched_context_once():
    """Without this, a cold pool of N costs 2N round-trips.

    `bulk_get_or_compute` batches only the cache READ; before this change every
    miss still issued its own `CandidateStage` and `CandidateConflict` SELECT
    inside `score_candidate_job`, so raising the pool to 1000 would have meant
    ~2000 queries per request.
    """
    for module, func in (
        ("app/services/match_score_cache.py", "bulk_get_or_compute"),
        ("app/services/scoring_service.py", "rank_candidates_for_job"),
    ):
        assert "build_job_scoring_context" in _calls_in(module, func), (
            f"{func} no longer prebuilds the per-job context — N+1 is back"
        )


def test_single_pair_callers_keep_the_unbatched_path():
    """`context=None` must stay valid: marketplace and justification score one pair."""
    src = (BACKEND / "app/services/scoring_service.py").read_text(encoding="utf-8")
    assert "context: Optional[JobScoringContext] = None" in src
    # The fallback query must still exist, or a None context would crash.
    assert "CandidateStage.screening_answers.is_not(None)" in src


def test_harness_can_measure_the_ceiling():
    """A knob we cannot measure is a knob we cannot defend."""
    src = (BACKEND / "scripts/eval_matching.py").read_text(encoding="utf-8")
    assert '"--pool"' in src, "no way to sweep pool sizes in the evaluator"
    assert "ranked_candidate_ids=ranked_ids," in src, (
        "ranked list truncated again — recall computed from the artefact would "
        "silently mean recall@20"
    )
