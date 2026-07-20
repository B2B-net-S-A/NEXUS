"""Regression test: a UID already imported by another user must not destroy
the second user's whole import batch.

PR-07 scoped the iCal upsert lookup by ``created_by`` to stop cross-user
overwrite (finding P0.8). But the DB carries a partial unique index on
``(external_source, external_id)`` WITHOUT ``created_by``
(``ux_calendar_events_external``, migration 0010). So for a UID another user
already owns, the scoped lookup misses, the importer INSERTs, and the unique
index raises IntegrityError at commit — rolling back the ENTIRE batch and
losing every event in that import.

The importer must instead skip the colliding UID (counted in
``skipped_conflict``), still persist every non-colliding event, and never
overwrite the other user's row.
"""

import uuid

import pytest
from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.calendar_event import CalendarEvent
from app.models.user import User, UserRole
from app.services import ical_import as ii


async def _seed_user() -> int:
    """calendar_events.created_by is an FK to users.id — need real rows."""
    unique = uuid.uuid4().hex[:8]
    async with AsyncSessionLocal() as db:
        u = User(
            email=f"m6-ical-{unique}@example.com",
            password_hash=hash_password(f"T3st_{unique}!M6"),
            name="M6 iCal",
            role=UserRole.recruiter,
            is_active=True,
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u.id


def _feed(uids_with_titles: list[tuple[str, str]]) -> bytes:
    """Minimal VCALENDAR with one VEVENT per (uid, title)."""
    body = "".join(
        "BEGIN:VEVENT\r\n"
        f"UID:{uid}\r\n"
        f"SUMMARY:{title}\r\n"
        "DTSTART:20990101T100000Z\r\n"
        "DTEND:20990101T110000Z\r\n"
        "END:VEVENT\r\n"
        for uid, title in uids_with_titles
    )
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n"
        f"{body}END:VCALENDAR\r\n"
    ).encode()


@pytest.mark.asyncio
async def test_shared_uid_does_not_destroy_second_users_import(monkeypatch):
    shared_uid = f"shared-{uuid.uuid4().hex[:10]}@example.com"
    own_uid = f"own-{uuid.uuid4().hex[:10]}@example.com"
    source = f"ical-test-{uuid.uuid4().hex[:8]}"
    user_a = await _seed_user()
    user_b = await _seed_user()

    # User A imports the shared UID.
    monkeypatch.setattr(
        ii, "_fetch_ical_safely", lambda url: _async(_feed([(shared_uid, "A owns")]))
    )
    async with AsyncSessionLocal() as db:
        res_a = await ii.import_ical_url(
            db, "https://feed.example/a.ics", source_tag=source, creator_id=user_a
        )
    assert res_a.inserted == 1, res_a.as_dict()

    # User B imports a feed containing the SAME UID plus one event of their
    # own. The collision must be skipped, not fatal.
    monkeypatch.setattr(
        ii,
        "_fetch_ical_safely",
        lambda url: _async(_feed([(shared_uid, "B tries"), (own_uid, "B owns")])),
    )
    async with AsyncSessionLocal() as db:
        res_b = await ii.import_ical_url(
            db, "https://feed.example/b.ics", source_tag=source, creator_id=user_b
        )

    # B's own event survived — the batch was NOT rolled back.
    assert res_b.inserted == 1, res_b.as_dict()
    assert res_b.skipped_conflict == 1, res_b.as_dict()
    assert res_b.errors == 0, res_b.as_dict()

    async with AsyncSessionLocal() as db:
        own = await db.scalar(
            select(CalendarEvent).where(
                CalendarEvent.external_source == source,
                CalendarEvent.external_id == own_uid,
            )
        )
        shared = await db.scalar(
            select(CalendarEvent).where(
                CalendarEvent.external_source == source,
                CalendarEvent.external_id == shared_uid,
            )
        )
    assert own is not None and own.created_by == user_b  # B's event persisted
    # A's event is untouched — no cross-user overwrite (P0.8).
    assert shared is not None
    assert shared.created_by == user_a
    assert shared.title == "A owns"


@pytest.mark.asyncio
async def test_duplicate_uid_within_one_feed_is_skipped(monkeypatch):
    """A feed repeating a UID must not trip the unique index at commit."""
    dup = f"dup-{uuid.uuid4().hex[:10]}@example.com"
    source = f"ical-test-{uuid.uuid4().hex[:8]}"
    user_c = await _seed_user()
    monkeypatch.setattr(
        ii,
        "_fetch_ical_safely",
        lambda url: _async(_feed([(dup, "first"), (dup, "second")])),
    )
    async with AsyncSessionLocal() as db:
        res = await ii.import_ical_url(
            db, "https://feed.example/d.ics", source_tag=source, creator_id=user_c
        )
    assert res.inserted == 1, res.as_dict()
    assert res.skipped_conflict == 1, res.as_dict()
    assert res.errors == 0, res.as_dict()


async def _async(value):
    """Await-able stand-in for the patched fetcher."""
    return value
