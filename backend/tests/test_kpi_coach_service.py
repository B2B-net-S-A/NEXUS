"""Unit tests for app.services.kpi_coach_service — pure helpers only.

Full integration flow (scheduler sweep → DB emit → WS push) is covered by
the E2E smoke-test on production (Chrome MCP), because the service binds
tightly to async SQLAlchemy sessions and the WebSocket singleton — mocking
all of that here would be heavier than a real e2e run.
"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.kpi_coach_service import is_in_quiet_hours

WARSAW = ZoneInfo("Europe/Warsaw")


# ── is_in_quiet_hours ──────────────────────────────────────────────────────
# (Nazwa myląca — w service to jest okno aktywnego coachingu, nie cisza.
# Zobacz komentarz w service dla refaktoru w fazie 2.)


def test_emit_window_active_on_weekday_morning():
    # Tuesday 10:00 Warsaw
    now = datetime(2026, 4, 21, 10, 0, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is True


def test_emit_window_active_on_weekday_at_17_30_edge():
    # Edge case: 17:30 is still within window (inclusive).
    now = datetime(2026, 4, 21, 17, 30, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is True


def test_emit_window_closed_before_9am():
    now = datetime(2026, 4, 21, 8, 59, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is False


def test_emit_window_closed_at_9_00_edge_is_open():
    # 9:00 sharp is the start of the workday — should be active.
    now = datetime(2026, 4, 21, 9, 0, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is True


def test_emit_window_closed_after_17_30():
    now = datetime(2026, 4, 21, 17, 31, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is False


def test_emit_window_closed_on_saturday():
    now = datetime(2026, 4, 25, 12, 0, tzinfo=WARSAW)  # Saturday
    assert is_in_quiet_hours(now) is False


def test_emit_window_closed_on_sunday():
    now = datetime(2026, 4, 26, 12, 0, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is False


def test_emit_window_accepts_utc_input():
    # 2026-04-21 08:00 UTC = 10:00 Warsaw (CEST) → active.
    from datetime import timezone

    now_utc = datetime(2026, 4, 21, 8, 0, tzinfo=timezone.utc)
    assert is_in_quiet_hours(now_utc) is True


def test_emit_window_friday_early_evening_closed():
    # Friday 17:31 — workday ended.
    now = datetime(2026, 4, 24, 17, 31, tzinfo=WARSAW)
    assert is_in_quiet_hours(now) is False
