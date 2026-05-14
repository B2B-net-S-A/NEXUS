"""Unit tests for `app.services.m365.calendar.parse_free_busy_response`.

Pure parser — covers the two response shapes Graph emits (`scheduleItems`
preferred, `availabilityView` fallback) and the per-schedule `error` case
that maps an out-of-tenant attendee to a single `unknown` slot.

No DB, no network. See:
https://learn.microsoft.com/en-us/graph/api/calendar-getschedule
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.m365.calendar import (
    _slots_from_availability_view,
    get_free_busy,
    parse_free_busy_response,
)


# ── parse_free_busy_response — scheduleItems path ────────────────────────────


def test_parse_schedule_items_busy_block() -> None:
    """When Graph returns explicit start/end pairs we use them verbatim."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "alice@example.com",
                "availabilityView": "022",
                "scheduleItems": [
                    {
                        "status": "busy",
                        "start": {
                            "dateTime": "2026-05-14T09:30:00.0000000",
                            "timeZone": "UTC",
                        },
                        "end": {
                            "dateTime": "2026-05-14T10:30:00.0000000",
                            "timeZone": "UTC",
                        },
                    }
                ],
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    assert list(parsed.keys()) == ["alice@example.com"]
    slots = parsed["alice@example.com"]
    assert len(slots) == 1
    assert slots[0]["status"] == "busy"
    assert slots[0]["start"] == datetime(2026, 5, 14, 9, 30, tzinfo=timezone.utc)
    assert slots[0]["end"] == datetime(2026, 5, 14, 10, 30, tzinfo=timezone.utc)


def test_parse_schedule_items_normalizes_z_suffix() -> None:
    """Graph occasionally returns trailing `Z` instead of explicit offset."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "bob@example.com",
                "scheduleItems": [
                    {
                        "status": "tentative",
                        "start": {
                            "dateTime": "2026-05-14T09:00:00Z",
                            "timeZone": "UTC",
                        },
                        "end": {"dateTime": "2026-05-14T09:30:00Z", "timeZone": "UTC"},
                    }
                ],
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    slots = parsed["bob@example.com"]
    assert slots[0]["status"] == "tentative"
    assert slots[0]["start"].tzinfo is timezone.utc


def test_parse_schedule_items_unknown_status_falls_back() -> None:
    """Graph may emit a status we don't map — never lie and call it `free`."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "carol@example.com",
                "scheduleItems": [
                    {
                        "status": "somethingWeird",
                        "start": {
                            "dateTime": "2026-05-14T09:00:00Z",
                            "timeZone": "UTC",
                        },
                        "end": {"dateTime": "2026-05-14T10:00:00Z", "timeZone": "UTC"},
                    }
                ],
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    assert parsed["carol@example.com"][0]["status"] == "unknown"


def test_parse_schedule_items_skips_malformed_entries() -> None:
    """A missing `start.dateTime` shouldn't blow up the whole response."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "dave@example.com",
                "scheduleItems": [
                    {"status": "busy"},  # no start/end at all
                    {
                        "status": "busy",
                        "start": {
                            "dateTime": "2026-05-14T09:00:00Z",
                            "timeZone": "UTC",
                        },
                        "end": {"dateTime": "2026-05-14T09:30:00Z", "timeZone": "UTC"},
                    },
                ],
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    # Only the well-formed item survives.
    assert len(parsed["dave@example.com"]) == 1


# ── parse_free_busy_response — availabilityView fallback ─────────────────────


def test_parse_uses_availability_view_when_no_items() -> None:
    """Some tenants return only the digit string — fall back to it."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "eve@example.com",
                "availabilityView": "002200",
                # scheduleItems intentionally omitted
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    slots = parsed["eve@example.com"]
    statuses = [s["status"] for s in slots]
    assert statuses == ["free", "free", "busy", "busy", "free", "free"]
    # First slot anchored at window_start, contiguous 30-min steps.
    assert slots[0]["start"] == window_start
    assert slots[1]["start"] == window_start + timedelta(minutes=30)
    assert slots[-1]["end"] == window_start + timedelta(minutes=180)


def test_availability_view_unknown_digit() -> None:
    """An unmapped digit (e.g. `9`) becomes `unknown`, not `free`."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    slots = _slots_from_availability_view("9", window_start, 30)
    assert slots[0]["status"] == "unknown"


# ── parse_free_busy_response — per-schedule error ────────────────────────────


def test_schedule_with_error_returns_unknown_window() -> None:
    """An attendee outside the tenant comes back with an `error` block — we
    flatten this to a single `unknown` slot so the UI can stay silent."""
    window_start = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    payload = {
        "value": [
            {
                "scheduleId": "external@gmail.com",
                "availabilityView": "0000",
                "scheduleItems": [],
                "error": {
                    "responseCode": "MailboxNotEnabledForRESTAPI",
                    "message": "...",
                },
            }
        ]
    }
    parsed = parse_free_busy_response(
        payload, window_start=window_start, interval_minutes=30
    )
    slots = parsed["external@gmail.com"]
    assert len(slots) == 1
    assert slots[0]["status"] == "unknown"
    assert slots[0]["start"] == window_start


def test_empty_value_array_returns_empty_map() -> None:
    parsed = parse_free_busy_response(
        {"value": []},
        window_start=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
        interval_minutes=30,
    )
    assert parsed == {}


def test_missing_value_key_returns_empty_map() -> None:
    """Defensive: don't KeyError if Graph returns an unexpected shape."""
    parsed = parse_free_busy_response(
        {},
        window_start=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
        interval_minutes=30,
    )
    assert parsed == {}


# ── get_free_busy input validation ───────────────────────────────────────────


async def test_get_free_busy_rejects_naive_datetimes() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        await get_free_busy(
            gc=None,  # type: ignore[arg-type]  # never reached
            attendees=["a@example.com"],
            start=datetime(2026, 5, 14, 9, 0),
            end=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
        )


async def test_get_free_busy_rejects_inverted_window() -> None:
    start = datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc)
    end = datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="end must be after start"):
        await get_free_busy(
            gc=None,  # type: ignore[arg-type]
            attendees=["a@example.com"],
            start=start,
            end=end,
        )


async def test_get_free_busy_rejects_more_than_20_attendees() -> None:
    """Graph caps at 20 schedules per call — surface the limit here so the
    caller doesn't get a confusing Graph 400."""
    attendees = [f"u{i}@example.com" for i in range(21)]
    with pytest.raises(ValueError, match="at most 20"):
        await get_free_busy(
            gc=None,  # type: ignore[arg-type]
            attendees=attendees,
            start=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
            end=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
        )


async def test_get_free_busy_empty_attendees_returns_empty_dict() -> None:
    """No-op when caller has nothing to ask about — avoids a wasted Graph call."""
    out = await get_free_busy(
        gc=None,  # type: ignore[arg-type]
        attendees=[],
        start=datetime(2026, 5, 14, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 5, 14, 10, 0, tzinfo=timezone.utc),
    )
    assert out == {}
