"""P0-A: an incomparable salary is scored NEUTRALLY, never full.

The candidate rate is PLN/hour and the legacy Job budget is PLN/month — there is
no conversion policy, so the pair is ``not_comparable``. It previously returned
the FULL salary budget, silently inflating the composite by the whole layer for
any candidate with a populated rate. It must return the neutral fraction (same
as missing data) — non-penalising but not over-crediting. Pure-function tests.
"""

from __future__ import annotations

from types import SimpleNamespace


def _cand(**kw):
    base = dict(expected_rate_hourly=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _job(**kw):
    base = dict(salary_min=None, salary_max=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_cross_unit_salary_is_neutral_not_full():
    from app.services.scoring_service import (
        DEFAULT_PROFILE,
        UNKNOWN_NEUTRAL_FRACTION,
        _score_salary,
    )

    # Canonical (blank) currency + hourly rate vs a monthly budget → not_comparable.
    cand = _cand(expected_rate_hourly=100)
    job = _job(salary_min=15000, salary_max=25000)

    r = _score_salary(cand, job)

    assert r.status == "not_comparable"
    assert r.points == DEFAULT_PROFILE.salary * UNKNOWN_NEUTRAL_FRACTION
    assert r.points < DEFAULT_PROFILE.salary  # never the full budget


def test_non_canonical_currency_is_neutral_not_full():
    from app.services.scoring_service import (
        DEFAULT_PROFILE,
        UNKNOWN_NEUTRAL_FRACTION,
        _score_salary,
    )

    cand = _cand(expected_rate_hourly=100, expected_rate_currency="USD")
    job = _job(salary_min=15000, salary_max=25000)

    r = _score_salary(cand, job)

    assert r.status == "not_comparable"
    assert r.points == DEFAULT_PROFILE.salary * UNKNOWN_NEUTRAL_FRACTION


def test_missing_data_stays_neutral():
    from app.services.scoring_service import (
        DEFAULT_PROFILE,
        UNKNOWN_NEUTRAL_FRACTION,
        _score_salary,
    )

    r = _score_salary(_cand(), _job())

    assert r.status == "unknown"
    assert r.points == DEFAULT_PROFILE.salary * UNKNOWN_NEUTRAL_FRACTION
