"""Runda 7 audytu — M365 (R7-V1-7, R7-N5-*). Testy bez bazy."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


def _graph_event(sensitivity: str = "private", change_key: str = "ck2") -> dict:
    return {
        "id": "graph-ev-r7",
        "changeKey": change_key,
        "subject": "Rozmowa",
        "body": {"content": "Treść"},
        "start": {"dateTime": "2026-10-01T10:00:00Z"},
        "end": {"dateTime": "2026-10-01T11:00:00Z"},
        "location": {"displayName": "Biuro"},
        "attendees": [{"emailAddress": {"address": "kandydat@example.com"}}],
        "sensitivity": sensitivity,
    }


def _existing_row(**extra):
    from app.models.calendar_event import EventType

    base = dict(
        title="Rozmowa",
        description="Treść",
        location="Biuro",
        attendees=[{"address": "kandydat@example.com"}],
        teams_link=None,
        online_meeting_url=None,
        m365_change_key="ck1",
        event_type=EventType.meeting,
        candidate_id=42,
        operational_owner_id=None,
    )
    base.update(extra)
    return SimpleNamespace(**base)


# ── R7-V1-7: prywatne spotkanie z Outlooka nie zostaje przy kandydacie ──────


async def test_meeting_turned_private_is_unlinked_from_candidate() -> None:
    from app.services.m365.sync import _upsert_event

    existing = _existing_row()
    db = AsyncMock()
    db.scalar.return_value = existing
    assert await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())
    assert existing.title == "Spotkanie prywatne"
    assert existing.candidate_id is None


async def test_already_scrubbed_but_linked_private_meeting_is_not_skipped() -> None:
    from app.services.m365.sync import _upsert_event

    existing = _existing_row(
        title="Spotkanie prywatne",
        description=None,
        location=None,
        attendees=[],
        m365_change_key="ck2",
    )
    db = AsyncMock()
    db.scalar.return_value = existing
    assert await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event())
    assert existing.candidate_id is None


async def test_normal_meeting_keeps_candidate_link() -> None:
    from app.services.m365.sync import _upsert_event

    existing = _existing_row()
    db = AsyncMock()
    db.scalar.side_effect = [existing, None]
    await _upsert_event(db, SimpleNamespace(user_id=5), _graph_event("normal"))
    assert existing.candidate_id == 42


async def test_old_private_scrub_unlinks_candidate() -> None:
    from app.services.m365 import sync as sync_mod

    class _Graph:
        async def get(self, url, params=None):
            return {"sensitivity": "private"}

    class _Scalars:
        def __init__(self, rows):
            self._rows = rows

        def all(self):
            return self._rows

    row = _existing_row(id=11, external_id="g-private")
    db = AsyncMock()
    db.get.return_value = None
    db.scalars.return_value = _Scalars([row])
    await sync_mod._scrub_old_private_events(
        db, _Graph(), SimpleNamespace(id=5, user_id=9)
    )
    assert row.title == "Spotkanie prywatne"
    assert row.candidate_id is None
