"""Przypomnienie „Klient milczy” co 14 dni — od ostatniego wysłania (audyt 24.09.2026).

Stara reguła ``dni % 14 == 0`` gubiła przypomnienie na kolejne 14 dni, gdy
poranny przebieg nie wypadł dokładnie w 14. dniu (pętla stała, deploy).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.request_allocation_notices import silent_reminder_due

NOW = datetime(2026, 9, 24, 8, 30, tzinfo=timezone.utc)


@pytest.mark.unit
def test_first_reminder_after_14_days_even_when_day_14_was_missed() -> None:
    since = NOW - timedelta(days=15)  # 14. dzień bez porannego przebiegu
    assert silent_reminder_due(NOW, since, None) is True
    assert silent_reminder_due(NOW, NOW - timedelta(days=13), None) is False


@pytest.mark.unit
def test_next_reminder_counts_from_the_last_one_sent() -> None:
    since = NOW - timedelta(days=40)
    assert (
        silent_reminder_due(NOW, since, (NOW - timedelta(days=13)).isoformat()) is False
    )
    assert (
        silent_reminder_due(NOW, since, (NOW - timedelta(days=15)).isoformat()) is True
    )


@pytest.mark.unit
def test_reminder_from_a_previous_silent_episode_does_not_count() -> None:
    since = NOW - timedelta(days=14)
    previous_episode = (since - timedelta(days=3)).isoformat()
    assert silent_reminder_due(NOW, since, previous_episode) is True


@pytest.mark.unit
def test_no_start_date_means_no_reminder() -> None:
    assert silent_reminder_due(NOW, None, None) is False
