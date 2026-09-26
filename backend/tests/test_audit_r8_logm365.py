"""Runda 8 audytu (LOGM365): prywatne spotkania z Outlooka i dzień notatki.

* R8-V3-3 — prywatne spotkania oczyszczone przed rundą 7 zachowały
  ``candidate_id`` (profil kandydata pokazywał „Spotkanie prywatne”, czyli
  z kim było): przebieg starych spotkań zdejmuje go także z wierszy już
  oczyszczonych, a jednorazowa korekta — z całej historii.
* R8-X1-5 — dzień notatki w prompcie liczony w Europe/Warsaw, nie w UTC.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from app.services.calendar_privacy import PRIVATE_EVENT_TITLE


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _NoGraph:
    """Wiersz już oczyszczony nie pyta Graphu — każde wywołanie to błąd testu."""

    async def get(self, url, params=None):  # pragma: no cover — nie może paść
        raise AssertionError(f"niepotrzebne zapytanie do Graphu: {url}")


@pytest.mark.asyncio
async def test_old_private_scrub_unlinks_candidate_from_already_scrubbed_row():
    from app.services.m365 import sync as sync_mod

    scrubbed = SimpleNamespace(
        id=71,
        external_id="g-old",
        title=PRIVATE_EVENT_TITLE,
        description=None,
        location=None,
        teams_link=None,
        online_meeting_url=None,
        attendees=[],
        candidate_id=5,
    )
    db = AsyncMock()
    db.get.return_value = None
    db.scalars.return_value = _Scalars([scrubbed])

    await sync_mod._scrub_old_private_events(
        db, _NoGraph(), SimpleNamespace(id=5, user_id=9)
    )

    assert scrubbed.candidate_id is None
    assert scrubbed.title == PRIVATE_EVENT_TITLE


# ── baza: jednorazowa korekta i dzień notatki ───────────────────────────────


async def _candidate(db) -> int:
    from app.models.candidate import Candidate

    suffix = uuid.uuid4().hex[:8]
    cand = Candidate(
        name="Ewa", lastname=f"Prywatna{suffix}", email=f"r8-{suffix}@example.com"
    )
    db.add(cand)
    await db.flush()
    return cand.id


@pytest.mark.asyncio
async def test_one_shot_repair_unlinks_only_scrubbed_private_outlook_events():
    from app.core.database import AsyncSessionLocal
    from app.models.app_setting import AppSetting
    from app.models.calendar_event import CalendarEvent, EventType
    from app.services.m365.calendar import M365_SOURCE
    from app.services.m365_private_event_link_repair import (
        run_private_event_unlink,
    )

    marker = f"test_r8_private_unlink_{uuid.uuid4().hex[:8]}"
    start = datetime.now(timezone.utc) - timedelta(days=400)
    async with AsyncSessionLocal() as db:
        cand_id = await _candidate(db)

        def _event(**extra) -> CalendarEvent:
            base = dict(
                title=PRIVATE_EVENT_TITLE,
                event_type=EventType.meeting,
                start_time=start,
                end_time=start + timedelta(hours=1),
                candidate_id=cand_id,
                attendees=[],
                external_source=M365_SOURCE,
                external_id=f"g-{uuid.uuid4().hex}",
            )
            base.update(extra)
            return CalendarEvent(**base)

        private = _event()
        regular = _event(title="Rozmowa z kandydatem")
        with_attendees = _event(attendees=[{"address": "x@example.com"}])
        db.add_all([private, regular, with_attendees])
        await db.commit()
        ids = (private.id, regular.id, with_attendees.id)

    async with AsyncSessionLocal() as db:
        summary = await run_private_event_unlink(db, marker=marker)
        await db.commit()
        assert summary is not None and private.id in summary["event_ids"]
        again = await run_private_event_unlink(db, marker=marker)
        assert again is None  # jednorazowa

    async with AsyncSessionLocal() as db:
        rows = {
            e.id: e.candidate_id
            for e in (
                await db.scalars(select(CalendarEvent).where(CalendarEvent.id.in_(ids)))
            ).all()
        }
        assert rows[ids[0]] is None
        assert rows[ids[1]] == cand_id
        assert rows[ids[2]] == cand_id
        for event_id in ids:
            await db.delete(await db.get(CalendarEvent, event_id))
        await db.delete(await db.get(AppSetting, marker))
        await db.commit()


@pytest.mark.asyncio
async def test_note_day_in_prompt_is_the_warsaw_day():
    from app.core.database import AsyncSessionLocal
    from app.models.note import Note
    from app.services.notes_insights_extractor import load_note_rows

    async with AsyncSessionLocal() as db:
        cand_id = await _candidate(db)
        # 30.09 22:30 UTC = 1.10 00:30 w Warszawie.
        note = Note(
            content="Dostępny od przyszłego miesiąca",
            candidate_id=cand_id,
            created_at=datetime(2026, 9, 30, 22, 30, tzinfo=timezone.utc),
        )
        db.add(note)
        await db.commit()

    async with AsyncSessionLocal() as db:
        rows = await load_note_rows(db, cand_id)
        assert rows[0][2] == date(2026, 10, 1)
        await db.delete(await db.get(Note, rows[0][0]))
        await db.commit()
