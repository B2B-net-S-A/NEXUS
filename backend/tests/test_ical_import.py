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


async def test_import_marks_date_only_events_as_all_day(monkeypatch):
    """`DTSTART;VALUE=DATE` = urlop/OOO. Bez flagi siatka rysowała blok 00:00–24:00,
    a pętla przypomnień budziła powiadomienie o północy (audyt 17.09.2026)."""
    import uuid

    from sqlalchemy import select

    from app.core.database import AsyncSessionLocal
    from app.models.calendar_event import CalendarEvent

    uid_all_day = f"all-day-{uuid.uuid4().hex}"
    uid_timed = f"timed-{uuid.uuid4().hex}"
    ics = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid_all_day}\r\nSUMMARY:Urlop\r\n"
        "DTSTART;VALUE=DATE:20410310\r\nDTEND;VALUE=DATE:20410312\r\n"
        "END:VEVENT\r\n"
        "BEGIN:VEVENT\r\n"
        f"UID:{uid_timed}\r\nSUMMARY:Rozmowa\r\n"
        "DTSTART:20410310T090000Z\r\nDTEND:20410310T100000Z\r\n"
        "END:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    ).encode()

    async def fake_fetch(url):
        return ics

    monkeypatch.setattr(ii, "_fetch_ical_safely", fake_fetch)
    async with AsyncSessionLocal() as db:
        result = await ii.import_ical_url(
            db, "https://example.com/cal.ics", since_days=0
        )
    assert result.inserted == 2, result.as_dict()

    async with AsyncSessionLocal() as db:
        rows = {
            row.external_id: row
            for row in (
                await db.scalars(
                    select(CalendarEvent).where(
                        CalendarEvent.external_id.in_([uid_all_day, uid_timed])
                    )
                )
            ).all()
        }
    assert rows[uid_all_day].all_day is True
    assert rows[uid_all_day].start_time == datetime(2041, 3, 10, tzinfo=timezone.utc)
    assert rows[uid_all_day].end_time == datetime(2041, 3, 12, tzinfo=timezone.utc)
    assert rows[uid_timed].all_day is False
