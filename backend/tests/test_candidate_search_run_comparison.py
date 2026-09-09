from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from scripts.compare_candidate_search_runs import compare_runs, recent_comparisons


def run(identity=1, population=2, **kwargs):
    return SimpleNamespace(
        id=str(UUID(int=identity)),
        population_size=population,
        state=kwargs.get("state", "complete"),
        created_by=kwargs.get("actor", 1),
        request_fingerprint=kwargs.get("fingerprint", "same-request"),
        version_trace=kwargs.get("versions", {"algorithm": "v1"}),
    )


def row(cid, score=60.729190826416016, **kwargs):
    return SimpleNamespace(
        candidate_id=cid,
        candidate_version=kwargs.get("version", "v1"),
        fit_score=score,
        state=kwargs.get("state", "evaluated"),
        eligible=kwargs.get("eligible", True),
        measurement=kwargs.get(
            "measurement", "measured" if score is not None else "stale"
        ),
    )


def test_exact_scores_and_ties_compare_independently_of_storage_order():
    result = compare_runs(run(), [row(2), row(1)], run(2), [row(1), row(2)])
    assert result["archived_parity_complete"]
    assert result["same_ranked_ids_and_order"]
    assert result["max_absolute_score_difference"] == 0
    assert result["comparable_measured_pairs"] == 2
    assert "candidate_ids" not in result


def test_partial_index_cannot_pass_full_parity_even_with_matching_scores():
    result = compare_runs(run(), [row(1), row(2, None)], run(2), [row(1), row(2, 80)])
    assert result["max_absolute_score_difference"] == 0
    assert result["comparable_measured_pairs"] == 1
    assert not result["left_ranking_complete"]
    assert not result["archived_parity_complete"]


@pytest.mark.parametrize("score", [60.9, float("nan"), float("inf"), True, -1, 101])
def test_score_drift_or_invalid_measurement_prevents_parity(score):
    result = compare_runs(run(1, 1), [row(1)], run(2, 1), [row(1, score)])
    assert not result["archived_parity_complete"]


def test_unknown_score_is_not_zero_and_small_tolerated_drift_is_explicit():
    empty = compare_runs(run(1, 1), [row(1, None)], run(2, 1), [row(1, None)])
    assert empty["max_absolute_score_difference"] is None
    assert not empty["archived_parity_complete"]
    result = compare_runs(run(1, 1), [row(1, 60)], run(2, 1), [row(1, 60.1)])
    assert result["archived_parity_complete"]
    assert result["max_absolute_score_difference"] == pytest.approx(0.1)


def test_population_membership_eligibility_and_version_differences_remain_visible():
    result = compare_runs(
        run(), [row(1), row(2)], run(2), [row(1, version="v2", eligible=False), row(3)]
    )
    assert not result["same_population"]
    assert result["changed_candidate_versions"] == 1
    assert result["eligibility_differences"] == 1
    assert not result["archived_parity_complete"]


@pytest.mark.parametrize(
    "changes",
    [
        {"actor": 2},
        {"fingerprint": "other"},
        {"versions": {"algorithm": "v2"}},
        {"state": "partial"},
    ],
)
def test_other_actor_context_or_unfinished_run_cannot_pass(changes):
    result = compare_runs(run(), [row(1), row(2)], run(2, **changes), [row(1), row(2)])
    assert not result["archived_parity_complete"]


def test_missing_or_duplicate_snapshot_is_rejected():
    with pytest.raises(ValueError, match="distinct runs"):
        compare_runs(run(), [row(1), row(2)], run(), [row(1), row(2)])
    with pytest.raises(ValueError, match="population snapshot"):
        compare_runs(run(), [row(1), row(1)], run(2), [row(1), row(2)])
    with pytest.raises(ValueError, match="population snapshot"):
        compare_runs(run(), [row(1)], run(2), [row(1), row(2)])


@pytest.mark.asyncio
async def test_recent_pair_selection_is_bounded_and_keeps_actor_and_context(
    monkeypatch,
):
    from scripts import compare_candidate_search_runs as module

    seen = []

    def compare(left, _left_rows, right, _right_rows):
        seen.append((left.id, right.id))
        return {"left_run_id": left.id, "right_run_id": right.id}

    monkeypatch.setattr(module, "compare_runs", compare)
    db = SimpleNamespace(
        execute=AsyncMock(return_value=SimpleNamespace(all=lambda: []))
    )
    searches = [
        run(1, state="running"),
        run(2),
        run(3, actor=2),
        run(4, fingerprint="other"),
        run(5),
    ]
    await recent_comparisons(db, searches)
    assert seen == [(run(2).id, run(5).id)]
    seen.clear()
    await recent_comparisons(db, [run(i) for i in range(1, 11)])
    assert len(seen) == 3
    with pytest.raises(ValueError):
        await recent_comparisons(db, [run(i) for i in range(1, 12)])
