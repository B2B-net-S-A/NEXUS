"""Licznik dzienny Jarvisa liczy od warszawskiej północy, nie od „północy UTC".

Do 22.09.2026 w oknie 00:00–02:00 czasu warszawskiego początek doby wypadał
w przyszłości i licznik pokazywał 0 (nocna grupa kolejki merge'ów padała na
`used_today >= 1`).
"""

from __future__ import annotations

from datetime import datetime, timezone

import time_machine

from app.api.jarvis import _today_start_utc


def test_just_after_warsaw_midnight_the_day_started_in_the_past():
    # 22.09 00:24 w Warszawie (lato, UTC+2) = 21.09 22:24 UTC.
    with time_machine.travel(
        datetime(2026, 9, 21, 22, 24, tzinfo=timezone.utc), tick=False
    ):
        start = _today_start_utc()
    assert start == datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)
    assert start <= datetime(2026, 9, 21, 22, 24, tzinfo=timezone.utc)


def test_winter_offset_is_one_hour():
    with time_machine.travel(
        datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc), tick=False
    ):
        assert _today_start_utc() == datetime(2026, 1, 14, 23, 0, tzinfo=timezone.utc)
