"""Unit tests for ical_import helpers (Phase 7b.6 / 7c)."""

from datetime import date, datetime, timezone

from app.services import ical_import as ii


def test_to_datetime_none_returns_none():
    assert ii._to_datetime(None) is None


def test_to_datetime_aware_datetime_preserves_tz():
    dt = datetime(2026, 4, 16, 14, 30, tzinfo=timezone.utc)
    assert ii._to_datetime(dt) == dt


def test_to_datetime_naive_datetime_adds_utc():
    dt = datetime(2026, 4, 16, 14, 30)
    r = ii._to_datetime(dt)
    assert r is not None
    assert r.tzinfo is timezone.utc
    assert r.hour == 14 and r.minute == 30


def test_to_datetime_date_converts_to_midnight_utc():
    d = date(2026, 4, 16)
    r = ii._to_datetime(d)
    assert r is not None
    assert r.year == 2026
    assert r.hour == 0 and r.minute == 0
    assert r.tzinfo is timezone.utc


def test_ical_import_result_as_dict():
    r = ii.ICalImportResult(
        source_url="https://example.com/cal.ics",
        events_fetched=10,
        inserted=7,
        updated=2,
        skipped_past=1,
        errors=0,
    )
    d = r.as_dict()
    assert d["source_url"].endswith("cal.ics")
    assert d["events_fetched"] == 10
    assert d["inserted"] == 7
    assert d["updated"] == 2
    assert d["skipped_past"] == 1
    assert d["errors"] == 0
    assert d["error_samples"] == []


def test_ical_import_result_caps_error_samples_at_20():
    r = ii.ICalImportResult(source_url="x")
    for i in range(30):
        r.error_samples.append(f"err {i}")
    assert len(r.as_dict()["error_samples"]) == 20
