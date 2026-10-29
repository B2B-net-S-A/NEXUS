"""Reguły „Rytmu dnia” (Insights, decyzje Artura 28.10.2026) — bez bazy."""

from datetime import date, datetime

import pytest

from app.services.work_rhythm import (
    DEFAULT_RULES,
    RHYTHM_START,
    clamp_window,
    day_index,
    diagnose,
    hour_level,
    hour_points,
    intensity_level,
    meeting_hours,
    period_index,
    rules_from_json,
    work_hours,
)

RULES = rules_from_json(None)


def test_defaults_match_decision():
    assert RULES.weights["screening"] == 5
    assert RULES.weights["action"] == 1
    assert RULES.hour_levels == (4, 11, 25)
    assert RULES.norm_work_hours == 7
    assert RULES.norm_day_points == 120


def test_partial_saved_rules_keep_defaults():
    rules = rules_from_json({"weights": {"screening": 8}, "norm_day_points": 100})
    assert rules.weights["screening"] == 8
    assert rules.weights["note"] == DEFAULT_RULES["weights"]["note"]
    assert rules.norm_day_points == 100
    assert rules.norm_work_hours == 7


def test_hour_points_use_weights_and_ignore_unknown_kinds():
    assert hour_points({"screening": 2, "action": 3, "nieznany": 10}, RULES) == 13


@pytest.mark.parametrize(
    ("points", "level"),
    [(0, 0), (0.5, 1), (3.5, 1), (4, 2), (10.9, 2), (11, 3), (24, 3), (25, 4), (80, 4)],
)
def test_hour_level_thresholds(points, level):
    assert hour_level(points, RULES) == level


def test_work_hours_count_meetings_without_actions_only_in_8_to_18():
    points = {7: 30.0, 9: 4.0, 10: 3.9, 18: 50.0}
    # 7 i 18 poza oknem, 10 za mało punktów, ale 10 i 14 mają spotkanie.
    assert work_hours(points, meetings=[10, 14], rules=RULES) == 3


def test_day_index_full_day_and_caps_at_100():
    points = {h: 30.0 for h in range(8, 18)}
    assert day_index(points, [], RULES) == 100


def test_day_index_half_and_half():
    # 7 godzin po 4 pkt = pełne pokrycie, 28 pkt z 120 = 0,23.
    points = {h: 4.0 for h in range(9, 16)}
    assert day_index(points, [], RULES) == round((1 + 28 / 120) / 2 * 100)


def test_full_leave_day_is_not_counted():
    assert day_index({9: 50.0}, [], RULES, available=0) is None


def test_half_day_leave_halves_the_norms():
    # 3,5 h po 4 pkt i 60 pkt to pełny dzień przy pół dnia urlopu.
    points = {9: 15.0, 10: 15.0, 11: 15.0, 12: 15.0}
    assert day_index(points, [], RULES, available=0.5) == 100
    assert day_index(points, [], RULES) < 100


def test_empty_working_day_is_zero_not_missing():
    assert day_index({}, [], RULES) == 0


def test_period_index_skips_leave_days():
    assert period_index([100, None, 50]) == 75
    assert period_index([None, None]) is None


@pytest.mark.parametrize(
    ("index", "level"), [(75, "high"), (74, "mid"), (50, "mid"), (49, "low")]
)
def test_intensity_levels(index, level):
    assert intensity_level(index, RULES) == level


@pytest.mark.parametrize(
    ("index", "pct", "diag"),
    [
        (90, 120, "model"),
        (90, 40, "quality"),
        (40, 120, "more_volume"),
        (40, 40, "more_work"),
        (60, 80, "model"),
        (59, 79, "more_work"),
    ],
)
def test_diagnosis_quadrants(index, pct, diag):
    assert diagnose(index, pct, RULES) == diag


def test_diagnosis_needs_both_numbers():
    assert diagnose(None, 100, RULES) is None
    assert diagnose(80, None, RULES) is None


def test_meeting_hours_need_30_minutes_in_the_hour():
    s = datetime(2026, 10, 20, 9, 40)
    e = datetime(2026, 10, 20, 11, 15)
    # 9:40–10:00 = 20 min (nie), 10–11 pełna, 11:00–11:15 = 15 min (nie).
    assert meeting_hours(s, e) == [(date(2026, 10, 20), 10)]


def test_window_defaults_to_last_10_business_days_but_not_before_12_10():
    start, end = clamp_window(None, None, today=date(2026, 10, 29))
    assert end == date(2026, 10, 29)
    assert start == date(2026, 10, 16)
    start, _ = clamp_window(None, None, today=date(2026, 10, 14))
    assert start == RHYTHM_START


def test_window_caps_length_and_future():
    start, end = clamp_window(
        date(2026, 10, 12), date(2027, 1, 31), today=date(2026, 12, 31)
    )
    assert end == date(2026, 12, 31)
    assert (end - start).days == 30


# ── Kto co widzi i odmowa złych reguł ───────────────────────────────────────


def _user(*roles):
    from app.models.user import User, UserRole

    return User(
        id=1,
        email="x@example.com",
        name="Test",
        role=UserRole(roles[0]),
        roles=list(roles),
    )


@pytest.mark.parametrize(
    ("roles", "allowed"),
    [
        (("recruiter",), False),
        (("talent_community_manager",), False),
        (("delivery_lead",), False),
        (("finance",), False),
        (("head_of_recruitment",), True),
        (("head_of_recruitment", "recruiter"), True),
        (("admin",), True),
    ],
)
def test_only_hor_and_admin_see_and_edit(roles, allowed):
    """Decyzja Artura 29.10.2026: na razie tylko Head of Recruitment i admin."""
    from app.api.insights_work_rhythm import can_edit_rules
    from app.services.work_rhythm import VIEWER_ROLES

    user = _user(*roles)
    assert user.has_any_role(*VIEWER_ROLES) is allowed
    assert can_edit_rules(user) is allowed


def _payload(**over):
    from app.services.work_rhythm import DEFAULT_RULES

    data = {**DEFAULT_RULES, "weights": dict(DEFAULT_RULES["weights"])}
    data.update(over)
    return data


def test_valid_rules_payload_round_trips():
    from app.api.insights_work_rhythm import WorkRhythmRulesIn

    parsed = WorkRhythmRulesIn(**_payload(norm_day_points=100))
    assert rules_from_json(parsed.model_dump()).norm_day_points == 100


@pytest.mark.parametrize(
    "over",
    [
        {"hour_levels": [11, 4, 25]},
        {"hour_levels": [4, 11]},
        {"level_mid": 80, "level_high": 75},
        {"weights": {"screening": 5}},
        {"weights": {**DEFAULT_RULES["weights"], "screening": 50}},
        {"norm_work_hours": 0},
    ],
)
def test_invalid_rules_are_refused(over):
    from pydantic import ValidationError

    from app.api.insights_work_rhythm import WorkRhythmRulesIn

    with pytest.raises(ValidationError):
        WorkRhythmRulesIn(**_payload(**over))


def test_days_before_account_creation_are_not_counted():
    from datetime import timezone

    from app.services.work_rhythm import account_start

    user = _user("recruiter")
    # 18.10 23:30 UTC = 19.10 01:30 w Warszawie.
    user.created_at = datetime(2026, 10, 18, 23, 30, tzinfo=timezone.utc)
    assert account_start(user) == date(2026, 10, 19)


def test_unfinished_today_does_not_enter_period_numbers():
    """Rano dzisiejszy dzień ma pół akcji — nie może zaniżać okresu (przegląd 29.10)."""
    from app.services.work_rhythm import summarize_days

    def d(index, *, in_progress=False):
        return {
            "before_start": False,
            "in_progress": in_progress,
            "leave": 0.0,
            "index": index,
            "work_hours": 5,
            "day_points": 80.0,
        }

    days = [d(64) for _ in range(9)] + [d(10, in_progress=True)]
    summary = summarize_days(days)
    assert summary["index"] == 64
    assert summary["worked_days"] == 9
    assert summary["leave_days"] == 0
