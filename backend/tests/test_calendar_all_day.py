"""Wpisy całodniowe: jedna reprezentacja z trzech źródeł (audyt 17.09.2026).

Urlop/OOO z Outlooka i z feedu iCal trafiał do bazy jako 24-godzinny blok
z `all_day=False`: siatka rysowała go przez cały dzień, zwężała rozmowy,
zgłaszała fałszywe kolizje i budziła przypomnienie o 01:45. Reprezentacja
to teraz „pływająca data": północ UTC dnia startu, koniec wyłączny.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from httpx import AsyncClient

from app.services.calendar_all_day import normalize_all_day
from app.services.ical_import import is_all_day_value
from app.services.m365.sync import EVENT_SELECT, _graph_event_fields

UTC = timezone.utc


def _utc(y: int, m: int, d: int, h: int = 0) -> datetime:
    return datetime(y, m, d, h, tzinfo=UTC)


def test_floating_date_stays_put() -> None:
    assert normalize_all_day(_utc(2026, 9, 21), _utc(2026, 9, 22)) == (
        _utc(2026, 9, 21),
        _utc(2026, 9, 22),
    )


def test_missing_or_non_positive_end_is_one_day() -> None:
    assert normalize_all_day(_utc(2026, 9, 21), None) == (
        _utc(2026, 9, 21),
        _utc(2026, 9, 22),
    )
    assert normalize_all_day(_utc(2026, 9, 21), _utc(2026, 9, 21))[1] == _utc(
        2026, 9, 22
    )


def test_local_warsaw_midnight_maps_to_the_local_date() -> None:
    # Północ w Warszawie latem = 22:00 UTC poprzedniego dnia.
    start = _utc(2026, 9, 20, 22)
    end = _utc(2026, 9, 22, 22)
    assert normalize_all_day(start, end) == (_utc(2026, 9, 21), _utc(2026, 9, 23))


def test_timed_range_covers_every_touched_day() -> None:
    # 10:00–15:00 lokalnie w jednym dniu = jeden dzień.
    assert normalize_all_day(_utc(2026, 9, 21, 8), _utc(2026, 9, 21, 13)) == (
        _utc(2026, 9, 21),
        _utc(2026, 9, 22),
    )


def test_graph_select_asks_for_is_all_day() -> None:
    assert "isAllDay" in EVENT_SELECT.split(",")


def test_graph_fields_mark_and_normalize_all_day() -> None:
    fields = _graph_event_fields(
        {
            "subject": "Urlop",
            "isAllDay": True,
            "start": {"dateTime": "2026-09-21T00:00:00.0000000"},
            "end": {"dateTime": "2026-09-24T00:00:00.0000000"},
        }
    )
    assert fields is not None
    assert fields["all_day"] is True
    assert fields["start_time"] == _utc(2026, 9, 21)
    assert fields["end_time"] == _utc(2026, 9, 24)


def test_graph_fields_timed_event_is_untouched() -> None:
    fields = _graph_event_fields(
        {
            "subject": None,
            "start": {"dateTime": "2026-09-21T08:30:00.0000000"},
            "end": {"dateTime": "2026-09-21T09:30:00.0000000"},
        }
    )
    assert fields is not None
    assert fields["all_day"] is False
    assert fields["title"] == "Spotkanie"
    assert fields["start_time"] == datetime(2026, 9, 21, 8, 30, tzinfo=UTC)


def test_graph_fields_without_start_are_skipped() -> None:
    assert _graph_event_fields({"subject": "x", "start": {}}) is None


def test_ical_date_value_is_all_day_but_datetime_is_not() -> None:
    assert is_all_day_value(date(2026, 9, 21)) is True
    assert is_all_day_value(datetime(2026, 9, 21, 10, tzinfo=UTC)) is False
    assert is_all_day_value(None) is False


async def test_manual_all_day_event_is_stored_as_floating_date(
    app_client: AsyncClient, app_auth_headers: dict
) -> None:
    resp = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Urlop ręczny",
            "all_day": True,
            "start_time": "2040-07-01T13:45:00+02:00",
            "end_time": "2040-07-02T09:00:00+02:00",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["all_day"] is True
    assert body["start_time"].startswith("2040-07-01T00:00:00")
    assert body["end_time"].startswith("2040-07-03T00:00:00")

    # Wpis całodniowy nie jest kolizją dla rozmowy tego dnia.
    interview = await app_client.post(
        "/api/calendar/events",
        headers=app_auth_headers,
        json={
            "title": "Rozmowa w dniu urlopu",
            "start_time": "2040-07-01T10:00:00+00:00",
            "end_time": "2040-07-01T11:00:00+00:00",
        },
    )
    assert interview.status_code == 201, interview.text
    conflicts = await app_client.get(
        "/api/calendar/conflicts",
        headers=app_auth_headers,
        params={
            "start": "2040-07-01T10:00:00+00:00",
            "end": (
                datetime(2040, 7, 1, 11, tzinfo=UTC) - timedelta(minutes=1)
            ).isoformat(),
        },
    )
    assert conflicts.status_code == 200, conflicts.text
    ids = {c["id"] for c in conflicts.json()["conflicts"]}
    assert body["id"] not in ids
    assert interview.json()["id"] in ids
