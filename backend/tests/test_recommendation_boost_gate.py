"""P0-A: historical-boost must never resurrect a hard-penalized candidate.

`_apply_historical_boost` adds the similar-jobs bonus to a breakdown's total,
but a breakdown whose composite was zeroed by a penalty (blacklist /
client-excluded / active conflict) must be skipped — otherwise the additive
boost could lift a blocked candidate back above the recommendation threshold.
Pure-function tests; no DB, no Qdrant.
"""

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


def test_boost_skips_penalized_breakdown():
    from app.api.recommendations import _apply_historical_boost

    penalized = _bd(1, 0.0, penalties=["client_excluded"])
    clean = _bd(2, 50.0)
    breakdowns = [penalized, clean]

    _apply_historical_boost(breakdowns, {1: 3, 2: 2})

    # A zeroed/penalized candidate is never boosted back above threshold.
    assert penalized.total == 0.0
    assert penalized.historical_boost == 0.0
    # An eligible candidate still gets its boost (2 sources -> +10).
    assert clean.total == 60.0
    assert clean.historical_boost == 10.0


def test_boost_noop_when_map_empty():
    from app.api.recommendations import _apply_historical_boost

    b = _bd(1, 40.0)
    _apply_historical_boost([b], {})
    assert b.total == 40.0
    assert b.historical_boost == 0.0


def test_boost_resorts_by_total_desc():
    from app.api.recommendations import _apply_historical_boost

    low = _bd(1, 40.0)
    high = _bd(2, 41.0)
    breakdowns = [low, high]

    # `low` gets a 3-source boost (+15 -> 55), overtaking `high`.
    _apply_historical_boost(breakdowns, {1: 3})

    assert [b.candidate_id for b in breakdowns] == [1, 2]
    assert breakdowns[0].total == 55.0
