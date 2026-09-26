"""Przypomnienie „Klient milczy” co 14 dni — od ostatniego wysłania (audyt 24.09.2026).

Stara reguła ``dni % 14 == 0`` gubiła przypomnienie na kolejne 14 dni, gdy
poranny przebieg nie wypadł dokładnie w 14. dniu (pętla stała, deploy).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.request_allocation_notices import (
    is_stale_check_day,
    silent_reminder_due,
)

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


@pytest.mark.unit
def test_monday_stale_check_uses_the_business_calendar_not_utc() -> None:
    """R5-7: przegląd o 00:30 w Warszawie w poniedziałek to niedziela w UTC."""
    monday_0030_warsaw = datetime(2026, 9, 27, 22, 30, tzinfo=timezone.utc)
    assert monday_0030_warsaw.weekday() == 6  # niedziela w UTC
    assert is_stale_check_day(monday_0030_warsaw) is True
    tuesday_0030_warsaw = datetime(2026, 9, 28, 22, 30, tzinfo=timezone.utc)
    assert tuesday_0030_warsaw.weekday() == 0  # poniedziałek w UTC
    assert is_stale_check_day(tuesday_0030_warsaw) is False
    assert is_stale_check_day(datetime(2026, 9, 28, 8, 0, tzinfo=timezone.utc)) is True


# ── Adresat „Requestów do decyzji” (runda 6 audytu) ─────────────────────────


@pytest.mark.unit
def test_inactive_or_missing_delivery_lead_escalates_to_head_of_recruitment() -> None:
    from app.services.request_allocation_notices import route_to_recipients

    assert route_to_recipients(7, {7}, [90, 91]) == [7]
    # Nieaktywny DL = jak brak DL-a — lustro `_delivery_lead_targets`.
    assert route_to_recipients(7, set(), [90, 91]) == [90, 91]
    assert route_to_recipients(None, {7}, [90]) == [90]


class _Rows:
    def __init__(self, items):
        self._items = items

    def all(self):
        return list(self._items)


class _FakeDb:
    """Pierwsze ``execute`` = wiersze rekrutacji, ``scalars`` = aktywni DL-e,
    potem Head of Recruitment."""

    def __init__(self, rows, active_leads, hor):
        self._rows = rows
        self._scalars = [active_leads, hor]

    async def execute(self, _statement):
        return _Rows(self._rows)

    async def scalars(self, _statement):
        return _Rows(self._scalars.pop(0))


@pytest.mark.asyncio
async def test_silent_reminder_for_inactive_lead_goes_to_hor_and_is_remembered(
    monkeypatch,
) -> None:
    from app.services import notification_triggers
    from app.services.request_allocation_notices import _review_notices

    sent: list[int] = []

    async def emit(db, **kwargs):
        sent.append(kwargs["user_id"])
        return object()

    monkeypatch.setattr(notification_triggers, "emit", emit)
    tuesday = datetime(2026, 9, 29, 7, 0, tzinfo=timezone.utc)
    rows = [(42, 7, "client_silent", tuesday - timedelta(days=40), None)]
    count, reminded = await _review_notices(
        _FakeDb(rows, active_leads=[], hor=[90]), now=tuesday, reminded={}
    )
    assert sent == [90]
    assert count == 1
    # Zapamiętane — jutro nie wraca (dotąd przepadało codziennie).
    assert reminded == {"42": tuesday.isoformat()}
