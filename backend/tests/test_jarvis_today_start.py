"""Początek dnia licznika Jarvisa to północ warszawska, nie północ UTC."""

from datetime import date, datetime, timezone

from app.api import jarvis


def test_day_start_is_warsaw_midnight_in_utc(monkeypatch):
    # 22.09 00:30 w Warszawie (CEST) = 21.09 22:30 UTC — dzień firmowy już 22.09.
    monkeypatch.setattr(jarvis, "business_today", lambda: date(2026, 9, 22))
    start = jarvis._today_start_utc()
    assert start == datetime(2026, 9, 21, 22, 0, tzinfo=timezone.utc)
    assert start <= datetime(2026, 9, 21, 22, 30, tzinfo=timezone.utc)


def test_day_start_in_winter_uses_cet(monkeypatch):
    monkeypatch.setattr(jarvis, "business_today", lambda: date(2026, 1, 15))
    assert jarvis._today_start_utc() == datetime(
        2026, 1, 14, 23, 0, tzinfo=timezone.utc
    )
