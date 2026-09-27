"""Runda 10 (R10-N10-10): dopisek deklaracji kandydata ma datę warszawską."""

from __future__ import annotations

from datetime import datetime, timezone

from app.api.public_engagement import _declaration_suffix


def test_note_date_is_the_warsaw_day_just_after_midnight():
    # 00:30 czasu warszawskiego 27.09 = 22:30 UTC 26.09.
    now = datetime(2026, 9, 26, 22, 30, tzinfo=timezone.utc)
    assert _declaration_suffix("  chętnie  ", now) == (
        "\n[deklaracja kandydata, 2026-09-27]: chętnie"
    )


def test_note_date_midday_is_unchanged():
    now = datetime(2026, 9, 27, 10, 0, tzinfo=timezone.utc)
    assert "2026-09-27" in _declaration_suffix("x", now)
