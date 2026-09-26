"""Runda 7 (R7-V1-6, R7-V1-7): odwołanie spotkań w Teams po usunięciu kandydata.

Bez bazy — sesja i Graph są atrapami.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.calendar_event import EventStatus
from app.services import followup_meetings as fm
from app.services.calendar_privacy import PRIVATE_EVENT_TITLE


class _Scalars:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return list(self._rows)


class _Session:
    def __init__(self, events):
        self.events = events
        self.committed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None

    async def scalars(self, _stmt):
        return _Scalars(self.events)

    async def commit(self):
        self.committed = True


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(fm, "_CANCEL_RETRY_DELAYS", (0.0, 0.0))


async def test_transient_graph_failure_is_retried(monkeypatch):
    calls = []

    async def cancel(upn, graph_id, comment):
        calls.append(graph_id)
        if len(calls) < 2:
            raise RuntimeError("503")
        return "cancelled"

    monkeypatch.setattr(fm.teams_prep_graph, "cancel_event", cancel)
    assert await fm.cancel_erased_meetings([("org@x.pl", "g1", 10)]) == 1
    assert calls == ["g1", "g1"]


async def test_failed_cancel_restores_event_as_scheduled(monkeypatch):
    async def cancel(upn, graph_id, comment):
        raise RuntimeError("graph down")

    event = SimpleNamespace(id=10, status=EventStatus.cancelled, description=None)
    session = _Session([event])
    monkeypatch.setattr(fm.teams_prep_graph, "cancel_event", cancel)
    monkeypatch.setattr("app.core.database.AsyncSessionLocal", lambda: session)

    assert await fm.cancel_erased_meetings([("org@x.pl", "g1", 10)]) == 0
    assert event.status == EventStatus.scheduled
    assert event.description == fm.CANCEL_FAILED_NOTE
    assert session.committed


class _EraseDb:
    def __init__(self, events):
        self.events = events

    async def execute(self, _stmt):
        return SimpleNamespace(all=lambda: [])

    async def scalars(self, _stmt):
        return _Scalars(self.events)

    async def flush(self):
        return None


async def test_erasure_keeps_private_meeting_title():
    private = SimpleNamespace(
        title=PRIVATE_EVENT_TITLE, description=None, attendees=[]
    )
    regular = SimpleNamespace(
        title="Prep 1: Jan Kowalski",
        description="opis",
        attendees=["jan@example.com", "rekruter@b2bnetwork.pl"],
    )
    candidate = SimpleNamespace(id=5, email="jan@example.com")
    _pending, counts = await fm.erase_candidate_meetings(
        _EraseDb([private, regular]), candidate
    )
    assert private.title == PRIVATE_EVENT_TITLE
    assert regular.title == fm.ERASED_EVENT_TITLE
    assert regular.attendees == ["rekruter@b2bnetwork.pl"]
    assert counts["calendar_events_anonymised"] == 2
