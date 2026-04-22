"""Unit tests for `app.core.scheduling` — timezone helpers bez DB."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from app.core.scheduling import (
    is_business_day,
    is_within_window,
    local_day_bounds,
    seconds_until_local_time,
)


WARSAW = ZoneInfo("Europe/Warsaw")


# ── local_day_bounds ─────────────────────────────────────────────────────────


def test_day_bounds_on_winter_day_utc_plus_1():
    now = datetime(2026, 1, 15, 10, 30, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    assert bounds.start_utc == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)
    assert bounds.end_utc.astimezone(WARSAW).date() == now.date()
    assert bounds.end_utc.astimezone(WARSAW).hour == 23
    assert bounds.end_utc.astimezone(WARSAW).minute == 59


def test_day_bounds_on_summer_day_utc_plus_2():
    now = datetime(2026, 7, 15, 10, 30, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    assert bounds.start_utc == datetime(2026, 7, 14, 22, 0, tzinfo=timezone.utc)


def test_day_bounds_around_dst_transition_spring():
    # W Polsce zmiana czasu zimowego → letniego: 30 marca 2025, 02:00 → 03:00.
    now = datetime(2025, 3, 30, 12, 0, tzinfo=WARSAW)
    bounds = local_day_bounds(now)
    # 30 marca zaczyna się o 23:00 UTC 29 marca (UTC+1 przed zmianą).
    assert bounds.start_utc == datetime(2025, 3, 29, 23, 0, tzinfo=timezone.utc)


def test_day_bounds_from_utc_input_converts_correctly():
    # Wejście w UTC — 00:30 UTC 16 stycznia = 01:30 Warsaw 16 stycznia.
    now_utc = datetime(2026, 1, 16, 0, 30, tzinfo=timezone.utc)
    bounds = local_day_bounds(now_utc)
    assert bounds.start_utc.astimezone(WARSAW).date() == (
        now_utc.astimezone(WARSAW).date()
    )


# ── is_business_day ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "iso_date,expected",
    [
        ("2026-04-20", True),   # Mon
        ("2026-04-21", True),   # Tue
        ("2026-04-24", True),   # Fri
        ("2026-04-25", False),  # Sat
        ("2026-04-26", False),  # Sun
    ],
)
def test_is_business_day(iso_date, expected):
    moment = datetime.fromisoformat(iso_date + "T10:00:00+02:00")
    assert is_business_day(moment) is expected


# ── is_within_window ─────────────────────────────────────────────────────────


def test_window_exact_match():
    now = datetime(2026, 4, 21, 11, 45, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is True


def test_window_within_5min_tolerance():
    now = datetime(2026, 4, 21, 11, 49, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is True


def test_window_outside_tolerance():
    now = datetime(2026, 4, 21, 11, 51, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45) is False


def test_window_custom_tolerance():
    now = datetime(2026, 4, 21, 11, 52, tzinfo=WARSAW)
    assert is_within_window(now, hour=11, minute=45, window_minutes=10) is True


# ── seconds_until_local_time ─────────────────────────────────────────────────


def test_seconds_until_future_target_today():
    now = datetime(2026, 4, 21, 10, 0, tzinfo=WARSAW)
    secs = seconds_until_local_time(now, hour=11, minute=45)
    # 1h 45min = 6300s
    assert secs == pytest.approx(6300, abs=1)


def test_seconds_until_target_passed_today_rolls_to_tomorrow():
    now = datetime(2026, 4, 21, 12, 0, tzinfo=WARSAW)
    secs = seconds_until_local_time(now, hour=11, minute=45)
    # Cel minął o 15 min → jutro = 23h 45min = 85500s
    assert secs == pytest.approx(23 * 3600 + 45 * 60, abs=1)
