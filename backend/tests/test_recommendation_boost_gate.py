"""Process history never changes fit, thresholds or ordering."""

from __future__ import annotations

from types import SimpleNamespace


def _bd(candidate_id: int, total: float, penalties=None):
    return SimpleNamespace(
        candidate_id=candidate_id,
        total=total,
        penalties=list(penalties or []),
        historical_boost=0.0,
        historical_sources_count=0,
    )


def test_history_keeps_both_penalized_and_clean_scores_unchanged():
    from app.api.recommendations import _annotate_historical_context

    penalized = _bd(1, 0.0, penalties=["client_excluded"])
    clean = _bd(2, 50.0)
    breakdowns = [penalized, clean]

    _annotate_historical_context(breakdowns, {1: 3, 2: 2})

    # A zeroed/penalized candidate is never boosted back above threshold.
    assert penalized.total == 0.0
    assert penalized.historical_boost == 0.0
    assert clean.total == 50.0
    assert clean.historical_boost == 0.0
    assert clean.historical_sources_count == 2


def test_boost_noop_when_map_empty():
    from app.api.recommendations import _annotate_historical_context

    b = _bd(1, 40.0)
    _annotate_historical_context([b], {})
    assert b.total == 40.0
    assert b.historical_boost == 0.0


def test_history_cannot_reorder_by_process_experience():
    from app.api.recommendations import _annotate_historical_context

    low = _bd(1, 40.0)
    high = _bd(2, 41.0)
    breakdowns = [low, high]

    # Three historical projects do not let a lower fit overtake a higher one.
    _annotate_historical_context(breakdowns, {1: 3})

    assert [b.candidate_id for b in breakdowns] == [2, 1]
    assert low.total == 40.0
    assert high.total == 41.0


def test_history_update_is_idempotent_and_ties_use_candidate_id():
    from app.api.recommendations import _annotate_historical_context

    rows = [_bd(2, 60), _bd(1, 60)]
    _annotate_historical_context(rows, {2: 8})
    _annotate_historical_context(rows, {2: 3})
    assert [(b.candidate_id, b.total) for b in rows] == [(1, 60), (2, 60)]
    assert rows[1].historical_sources_count == 3
    assert rows[1].historical_boost == 0
