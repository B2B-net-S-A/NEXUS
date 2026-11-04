"""„Zmiany od wczoraj” na daily liczą się od poprzedniego dnia roboczego.

Do 04.10.2026 okno miało stałe 24 h, więc w poniedziałek daily nie widziało
zmian z piątku. Teraz: ta sama godzina poprzedniego dnia roboczego (polskie
święta jak w `core.scheduling.is_business_day`).
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.services.request_allocation import changed_since


def test_tuesday_looks_back_to_monday() -> None:
    now = datetime(2026, 10, 6, 8, 0, tzinfo=timezone.utc)  # wtorek
    assert changed_since(now) == datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)


def test_monday_looks_back_to_friday() -> None:
    now = datetime(2026, 10, 5, 8, 0, tzinfo=timezone.utc)  # poniedziałek
    assert changed_since(now) == datetime(2026, 10, 2, 8, 0, tzinfo=timezone.utc)


def test_day_after_a_holiday_skips_it() -> None:
    # 11.11.2026 (środa) to Święto Niepodległości — czwartek patrzy na wtorek.
    now = datetime(2026, 11, 12, 8, 0, tzinfo=timezone.utc)
    assert changed_since(now) == datetime(2026, 11, 10, 8, 0, tzinfo=timezone.utc)


def test_window_never_reaches_further_than_a_week() -> None:
    now = datetime(2026, 12, 28, 8, 0, tzinfo=timezone.utc)
    assert (now - changed_since(now)).days <= 7
