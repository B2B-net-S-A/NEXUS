"""Praktykant — czyste reguły listy telefonów (0371), bez bazy."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import trainee_rules as r

NOW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


def _row(**kw):
    base = {
        "expected_rate_hourly": Decimal("150"),
        "profile_rate_updated_at": NOW - timedelta(days=10),
        "b2b_willingness": "b2b",
        "work_time_preference": "also_part_time",
        "preferences": {"remote_modes": ["hybrid"]},
        "max_onsite_days_per_week": 2,
        "accepts_below_min_rate": True,
        "accepts_more_office_days": False,
        "availability_status": "open_to_offers",
        "availability_date": None,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_complete_profile_has_no_missing_codes() -> None:
    assert r.missing_codes(_row(), r.DEFAULT_RULES, now=NOW) == []


def test_each_gap_is_reported_with_its_code() -> None:
    row = _row(
        expected_rate_hourly=None,
        b2b_willingness=None,
        work_time_preference=None,
        preferences={},
        max_onsite_days_per_week=None,
        accepts_below_min_rate=None,
        accepts_more_office_days=None,
        availability_status="unknown",
    )
    assert r.missing_codes(row, r.DEFAULT_RULES, now=NOW) == [
        "rate_missing",
        "b2b",
        "work_time",
        "work_mode",
        "below_min_consent",
        "office_consent",
        "availability",
    ]


def test_rate_older_than_rule_is_stale() -> None:
    row = _row(profile_rate_updated_at=NOW - timedelta(days=200))
    assert r.missing_codes(row, r.DEFAULT_RULES, now=NOW) == ["rate_stale"]


def test_disabled_rule_does_not_report_its_gap() -> None:
    rules = r.normalize_rules({"missing_b2b": False})
    assert "b2b" not in r.missing_codes(_row(b2b_willingness=None), rules, now=NOW)


def test_rules_are_clamped_and_unknown_keys_dropped() -> None:
    rules = r.normalize_rules(
        {"min_fits": 999, "window_months": "0", "missing_rate": "yes", "evil": 1}
    )
    assert rules["min_fits"] == 20
    assert rules["window_months"] == 1
    assert rules["missing_rate"] is True  # nie-bool nie nadpisuje
    assert "evil" not in rules


def test_program_counts_polish_workdays() -> None:
    # 1–30.11.2026: 1.11 (niedziela) i 11.11 (środa) wolne.
    start = date(2026, 11, 2)
    assert r.workdays_between(start, date(2026, 11, 13)) == 9
    assert r.program_end_date(start, 10) == date(2026, 11, 16)


def test_program_starting_on_weekend_starts_next_workday() -> None:
    assert r.program_end_date(date(2026, 9, 26), 1) == date(2026, 9, 28)


def _job(job_id, skills, cc=None, is_open=True):
    return r.DemandJob(
        id=job_id,
        skills=frozenset(skills),
        competence_category_id=cc,
        is_open=is_open,
    )


def test_fit_needs_sixty_percent_of_must_haves() -> None:
    job = _job(1, {"java", "spring", "kafka"})
    assert r.job_fits(frozenset({"java", "spring"}), None, job)
    assert not r.job_fits(frozenset({"java"}), None, job)


def test_fit_rejects_other_competence_category() -> None:
    job = _job(1, {"java"}, cc=2)
    assert not r.job_fits(frozenset({"java"}), 3, job)
    assert r.job_fits(frozenset({"java"}), None, job)


def test_demand_counts_open_fits_and_orders_stack() -> None:
    index = r.build_index(
        [
            _job(1, {"java", "spring"}),
            _job(2, {"java"}, is_open=False),
            _job(3, {"python"}),
        ]
    )
    demand = r.demand_for(frozenset({"java", "spring"}), None, index)
    assert demand.fits == 2
    assert demand.open_fits == 1
    assert demand.stack[0] == "java"
    assert demand.job_ids == (1, 2)


def test_ranking_prefers_open_recruitments_then_count_then_gaps() -> None:
    a = r.Demand(fits=5, open_fits=0, stack=(), job_ids=())
    b = r.Demand(fits=2, open_fits=1, stack=(), job_ids=())
    keys = sorted([(r.rank_key(1, a, ["b2b"]), "a"), (r.rank_key(2, b, ["b2b"]), "b")])
    assert [name for _, name in keys] == ["b", "a"]


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [
        (150, "hour", Decimal("150.00")),
        (1200, "day", Decimal("150.00")),
        (25200, "month", Decimal("150.00")),
    ],
)
def test_min_rate_converts_to_hourly(value, unit, expected) -> None:
    assert r.hourly_min_rate(value, unit) == expected


@pytest.mark.parametrize(
    ("value", "unit"), [(0, "hour"), (-5, "hour"), (5000, "hour"), (1, "week")]
)
def test_min_rate_rejects_nonsense(value, unit) -> None:
    with pytest.raises(ValueError):
        r.hourly_min_rate(value, unit)


def test_answered_pct() -> None:
    assert r.answered_pct(3, 1) == 75.0
    assert r.answered_pct(0, 0) is None
