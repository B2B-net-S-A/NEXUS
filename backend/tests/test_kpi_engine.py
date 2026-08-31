"""Unit tests dla kpi_engine — pure logika bez DB.

Pokrywa:
- period_bounds (day/week/month — granice kalendarzowe w Europe/Warsaw)
- period_bucket_label (dedup keys)
- expected_progress_ratio (dzień roboczy 9:00-17:30)
- derive_state (hit / behind / on_track / ahead / missed)
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.services.kpi_catalog import KpiPeriod
from app.services.kpi_engine import (
    _hours_until_period_end,
    derive_state,
    expected_progress_ratio,
    period_bounds,
    period_bucket_label,
)

WARSAW = ZoneInfo("Europe/Warsaw")


# ── period_bounds ───────────────────────────────────────────────────────


def test_period_bounds_day_starts_at_local_midnight():
    # Poniedziałek 14:30 Warsaw
    now = datetime(2026, 4, 20, 14, 30, tzinfo=WARSAW)
    start, end = period_bounds(KpiPeriod.day, now)
    assert start == datetime(2026, 4, 20, 0, 0, tzinfo=WARSAW)
    assert end == now


def test_period_bounds_week_starts_on_monday():
    # Czwartek 2026-04-23 → week start = poniedziałek 2026-04-20
    now = datetime(2026, 4, 23, 10, 0, tzinfo=WARSAW)
    start, end = period_bounds(KpiPeriod.week, now)
    assert start == datetime(2026, 4, 20, 0, 0, tzinfo=WARSAW)
    assert start.weekday() == 0  # monday
    assert end == now


def test_period_bounds_week_on_monday_itself():
    # Monday 00:30 → week start = today 00:00
    now = datetime(2026, 4, 20, 0, 30, tzinfo=WARSAW)
    start, _ = period_bounds(KpiPeriod.week, now)
    assert start == datetime(2026, 4, 20, 0, 0, tzinfo=WARSAW)


def test_period_bounds_week_on_sunday_takes_prev_monday():
    # Sunday 2026-04-26 23:00 → week start = 2026-04-20
    now = datetime(2026, 4, 26, 23, 0, tzinfo=WARSAW)
    start, _ = period_bounds(KpiPeriod.week, now)
    assert start == datetime(2026, 4, 20, 0, 0, tzinfo=WARSAW)


def test_period_bounds_month_starts_at_first_day():
    now = datetime(2026, 4, 21, 14, 30, tzinfo=WARSAW)
    start, end = period_bounds(KpiPeriod.month, now)
    assert start == datetime(2026, 4, 1, 0, 0, tzinfo=WARSAW)
    assert end == now


def test_period_bounds_accepts_utc_input_and_converts():
    # Funkcja powinna pracować w strefie Warsaw — jeśli dostanie UTC,
    # powinna przekonwertować do Warsaw przed wyliczeniem granicy dnia.
    now_utc = datetime(2026, 4, 20, 22, 30, tzinfo=timezone.utc)
    # To jest 2026-04-21 00:30 Warsaw — czyli nowy dzień lokalnie.
    start, _ = period_bounds(KpiPeriod.day, now_utc)
    # Start dnia Warsaw = 2026-04-21 00:00 Warsaw = 2026-04-20 22:00 UTC
    expected = datetime(2026, 4, 21, 0, 0, tzinfo=WARSAW)
    assert start == expected


# ── period_bucket_label ─────────────────────────────────────────────────


def test_period_bucket_label_day():
    now = datetime(2026, 4, 21, 14, 30, tzinfo=WARSAW)
    assert period_bucket_label(KpiPeriod.day, now) == "2026-04-21"


def test_period_bucket_label_week_iso_format():
    # Tuesday 2026-04-21 → ISO week 17
    now = datetime(2026, 4, 21, 14, 30, tzinfo=WARSAW)
    assert period_bucket_label(KpiPeriod.week, now) == "2026-W17"


def test_period_bucket_label_week_pads_to_two_digits():
    # 2026-01-05 = ISO week 02 → "2026-W02"
    now = datetime(2026, 1, 5, 10, 0, tzinfo=WARSAW)
    assert period_bucket_label(KpiPeriod.week, now) == "2026-W02"


def test_period_bucket_label_month():
    now = datetime(2026, 4, 21, 14, 30, tzinfo=WARSAW)
    assert period_bucket_label(KpiPeriod.month, now) == "2026-04"


# ── expected_progress_ratio ─────────────────────────────────────────────


def test_expected_progress_ratio_before_workday_starts_is_zero():
    now = datetime(2026, 4, 21, 8, 0, tzinfo=WARSAW)  # przed 9:00
    assert expected_progress_ratio(KpiPeriod.day, now) == 0.0


def test_expected_progress_ratio_at_workday_start_is_zero():
    now = datetime(2026, 4, 21, 9, 0, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.day, now) == 0.0


def test_expected_progress_ratio_at_workday_end_is_one():
    now = datetime(2026, 4, 21, 17, 30, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.day, now) == pytest.approx(1.0)


def test_expected_progress_ratio_after_workday_end_is_one():
    now = datetime(2026, 4, 21, 22, 0, tzinfo=WARSAW)
    assert expected_progress_ratio(KpiPeriod.day, now) == pytest.approx(1.0)


def test_daily_deadline_hours_use_workday_end():
    now = datetime(2026, 4, 21, 15, 0, tzinfo=WARSAW)
    assert _hours_until_period_end(KpiPeriod.day, now) == pytest.approx(2.5)


def test_daily_deadline_hours_are_zero_after_workday_end():
    now = datetime(2026, 4, 21, 18, 0, tzinfo=WARSAW)
    assert _hours_until_period_end(KpiPeriod.day, now) == 0.0


def test_daily_deadline_hours_convert_utc_to_warsaw():
    # 13:00 UTC = 15:00 Europe/Warsaw in April.
    now = datetime(2026, 4, 21, 13, 0, tzinfo=timezone.utc)
    assert _hours_until_period_end(KpiPeriod.day, now) == pytest.approx(2.5)


def test_expected_progress_ratio_midday():
    # 13:15 → środek dnia roboczego (9:00-17:30 = 8.5h, 13:15 = +4.25h)
    now = datetime(2026, 4, 21, 13, 15, tzinfo=WARSAW)
    ratio = expected_progress_ratio(KpiPeriod.day, now)
    assert 0.49 < ratio < 0.51  # ~0.5


def test_expected_progress_ratio_week_scales_by_weekday():
    # Wtorek (weekday=1) 17:30 → skończony 2 dzień z 5 = 40%
    now = datetime(2026, 4, 21, 17, 30, tzinfo=WARSAW)
    ratio = expected_progress_ratio(KpiPeriod.week, now)
    assert 0.39 < ratio < 0.41


def test_expected_progress_ratio_week_end_of_friday_is_one():
    now = datetime(2026, 4, 24, 17, 30, tzinfo=WARSAW)  # piątek koniec dnia
    ratio = expected_progress_ratio(KpiPeriod.week, now)
    assert ratio == pytest.approx(1.0)


def test_expected_progress_ratio_week_weekend_caps_at_one():
    now = datetime(2026, 4, 25, 12, 0, tzinfo=WARSAW)  # sobota
    ratio = expected_progress_ratio(KpiPeriod.week, now)
    assert ratio == pytest.approx(1.0)


def test_expected_progress_ratio_month_mid():
    # 15 kwietnia 17:30, miesiąc ma 30 dni → ~15/30 = 0.5
    now = datetime(2026, 4, 15, 17, 30, tzinfo=WARSAW)
    ratio = expected_progress_ratio(KpiPeriod.month, now)
    assert 0.48 < ratio < 0.52


# ── derive_state ────────────────────────────────────────────────────────


def test_derive_state_hit_when_current_meets_target():
    assert derive_state(current=10, target=10, expected_ratio=0.5) == "hit"
    assert derive_state(current=15, target=10, expected_ratio=0.5) == "hit"


def test_derive_state_zero_target_is_hit_always():
    # target=0 (nie dotyczy tej roli) — zawsze "hit" żeby nie spamować.
    assert derive_state(current=0, target=0, expected_ratio=0.3) == "hit"


def test_derive_state_behind_when_current_below_expected_threshold():
    # expected_ratio=0.5, target=10 → expected=5. behind jeśli current < 5*0.8=4.
    assert derive_state(current=3, target=10, expected_ratio=0.5) == "behind"
    assert derive_state(current=0, target=10, expected_ratio=0.5) == "behind"


def test_derive_state_on_track_when_near_expected():
    # expected_ratio=0.5, target=10 → expected=5. on_track między 4 a 6.
    assert derive_state(current=5, target=10, expected_ratio=0.5) == "on_track"
    assert derive_state(current=4, target=10, expected_ratio=0.5) == "on_track"


def test_derive_state_ahead_when_above_expected():
    # expected_ratio=0.5, target=10 → expected=5. ahead jeśli current >= 5*1.2=6.
    assert derive_state(current=7, target=10, expected_ratio=0.5) == "ahead"


def test_derive_state_missed_only_after_period_ends():
    # Current < target, ratio = 1.0 (okres się skończył) → missed.
    assert derive_state(current=7, target=10, expected_ratio=1.0) == "missed"


def test_derive_state_behind_before_workday_starts_is_neutral():
    # expected_ratio=0.0 (przed 9:00) — nie ma sensu mówić "behind".
    # 0 akcji przy 0% expected → on_track, nie behind.
    assert derive_state(current=0, target=10, expected_ratio=0.0) == "on_track"
