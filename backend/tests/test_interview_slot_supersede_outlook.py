"""Przełożenie rozmowy u klienta mówi prawdę o blokadzie w Outlooku.

Runda 7 (R7-V3-3): gdy odwołanie w Outlooku rekrutera się nie udało (Graph
5xx/429, wygasły token) albo skrzynka nie była połączona, stara rozmowa
dostawała ``cancelled``, a okno i toast mówiły „Poprzedni termin odwołany” —
blokada zostawała w kalendarzu bez słowa. ``_cancel_outlook_copy`` zwraca
teraz stan, który trafia do odpowiedzi potwierdzenia.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import interview_slots
from app.services.m365 import calendar as m365_calendar
from app.services.m365.graph_client import GraphRequestError


class _Nested:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Db:
    def __init__(self, conn):
        self._conn = conn

    async def scalar(self, _statement):
        return self._conn

    def begin_nested(self):
        return _Nested()


def _event(**kw):
    base = dict(
        id=9,
        external_source=m365_calendar.M365_SOURCE,
        external_id="AAMk-1",
        created_by=3,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_graph_failure_is_reported_not_swallowed(monkeypatch):
    async def boom(db, conn, external_id):
        raise GraphRequestError(503, "unavailable")

    monkeypatch.setattr(m365_calendar, "cancel_graph_event", boom)
    db = _Db(SimpleNamespace(is_active=True))
    assert await interview_slots._cancel_outlook_copy(db, _event()) == "failed"


@pytest.mark.asyncio
async def test_cancelled_in_outlook(monkeypatch):
    calls = []

    async def ok(db, conn, external_id):
        calls.append(external_id)

    monkeypatch.setattr(m365_calendar, "cancel_graph_event", ok)
    db = _Db(SimpleNamespace(is_active=True))
    assert await interview_slots._cancel_outlook_copy(db, _event()) == "cancelled"
    assert calls == ["AAMk-1"]


@pytest.mark.asyncio
async def test_disconnected_mailbox_is_reported():
    assert (
        await interview_slots._cancel_outlook_copy(
            _Db(SimpleNamespace(is_active=False)), _event()
        )
        == "not_connected"
    )
    assert await interview_slots._cancel_outlook_copy(_Db(None), _event()) == (
        "not_connected"
    )


@pytest.mark.asyncio
async def test_nexus_only_interview_has_nothing_in_outlook():
    assert (
        await interview_slots._cancel_outlook_copy(
            _Db(None), _event(external_source="manual", external_id=None)
        )
        == "none"
    )
