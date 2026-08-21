"""Jedna synchronizacja na skrzynkę naraz (bramka `single-flight`).

Regresja tutaj jest CICHA i droga. `last_sync_status = running` był
zapisywany i przez nic nie czytany, więc gdy backfill z callbacku OAuth
(12 miesięcy historii, godziny pracy) trwał, zaplanowana pętla po 300 s
brała TĘ SAMĄ skrzynkę drugi raz. Skutki: podwojony ruch do Graph względem
limitu throttlingu rekrutera, dwa pobrania każdego załącznika, wyścig na
kursorze delta (`setattr(conn, cursor_attr, ...)` z dwóch sesji) oraz
kolizja na UNIQUE `emails.m365_message_id`, po której commit strony
odrzucał komplet zaciągniętych maili. Nic z tego nie było widać:
`/api/health` przez cały czas raportuje `m365: healthy`.

Testy sterują `sync_connection` bez bazy i bez Graph — sprawdzają samą
bramkę, bo to ona jest jedynym miejscem, przez które przechodzą wszystkie
cztery ścieżki wywołania (pętla, `trigger_backfill`, webhook, `/sync/trigger`).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.models.m365 import M365SyncStatus
from app.services.m365 import sync as sync_mod

pytestmark = pytest.mark.asyncio


class _FakeDB:
    """Sesja-atrapa: `sync_connection` potrzebuje wyłącznie `commit`."""

    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1


class _FakeGraphClient:
    def __init__(self, conn, db):  # noqa: D107 — atrapa
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _conn(connection_id: int = 1):
    return SimpleNamespace(
        id=connection_id,
        user_id=1,
        last_sync_status=M365SyncStatus.idle,
        last_sync_at=None,
        last_error=None,
    )


@pytest.fixture(autouse=True)
def _isolate_locks(monkeypatch):
    """Świeży rejestr locków na test — inaczej kolejność testów ma znaczenie."""
    monkeypatch.setattr(sync_mod, "_sync_locks", {})

    async def _eligible(_db, _conn):
        return True

    monkeypatch.setattr(sync_mod, "connection_owner_is_eligible", _eligible)
    monkeypatch.setattr(sync_mod, "GraphClient", _FakeGraphClient)


async def test_second_sync_of_the_same_mailbox_is_refused_while_the_first_runs(
    monkeypatch,
):
    started = asyncio.Event()
    release = asyncio.Event()
    runs = 0

    async def _slow_messages(db, gc, conn, result):
        nonlocal runs
        runs += 1
        started.set()
        await release.wait()

    async def _noop_events(db, gc, conn, result):
        return None

    monkeypatch.setattr(sync_mod, "_sync_messages", _slow_messages)
    monkeypatch.setattr(sync_mod, "_sync_events", _noop_events)

    conn = _conn()
    first = asyncio.create_task(sync_mod.sync_connection(_FakeDB(), conn))
    await asyncio.wait_for(started.wait(), timeout=5)

    # Druga ścieżka (np. tik pętli w trakcie backfillu z OAuth) — musi odbić się
    # od bramki, a nie ruszyć równolegle ani zawisnąć w kolejce za backfillem.
    second = await asyncio.wait_for(
        sync_mod.sync_connection(_FakeDB(), _conn()), timeout=5
    )

    assert second.skipped_already_running is True
    assert second.messages_ingested == 0
    assert runs == 1, "drugi przebieg wszedł do środka — bramka nie działa"

    release.set()
    first_result = await asyncio.wait_for(first, timeout=5)
    assert first_result.skipped_already_running is False
    assert conn.last_sync_status == M365SyncStatus.idle


async def test_different_mailboxes_do_not_block_each_other(monkeypatch):
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_messages(db, gc, conn, result):
        if conn.id == 1:
            started.set()
            await release.wait()

    async def _noop_events(db, gc, conn, result):
        return None

    monkeypatch.setattr(sync_mod, "_sync_messages", _slow_messages)
    monkeypatch.setattr(sync_mod, "_sync_events", _noop_events)

    first = asyncio.create_task(sync_mod.sync_connection(_FakeDB(), _conn(1)))
    await asyncio.wait_for(started.wait(), timeout=5)

    other = await asyncio.wait_for(
        sync_mod.sync_connection(_FakeDB(), _conn(2)), timeout=5
    )
    assert other.skipped_already_running is False

    release.set()
    await asyncio.wait_for(first, timeout=5)


async def test_lock_is_released_when_the_pass_blows_up(monkeypatch):
    """Padnięty przebieg nie może zamurować skrzynki na zawsze.

    `sync_connection` łapie wyjątki wewnątrz, ale lock musi zwolnić się także
    wtedy, gdy coś ucieknie — inaczej jeden błąd wyłącza synchronizację tej
    skrzynki do restartu kontenera, bez śladu w `/api/health`.
    """

    async def _boom(db, gc, conn, result):
        raise RuntimeError("Graph padł")

    async def _noop_events(db, gc, conn, result):
        return None

    monkeypatch.setattr(sync_mod, "_sync_messages", _boom)
    monkeypatch.setattr(sync_mod, "_sync_events", _noop_events)

    conn = _conn()
    failed = await sync_mod.sync_connection(_FakeDB(), conn)
    assert failed.errors == 1
    assert conn.last_sync_status == M365SyncStatus.error

    # Kolejne wywołanie musi wejść do środka, a nie odbić się od bramki.
    again = await sync_mod.sync_connection(_FakeDB(), _conn())
    assert again.skipped_already_running is False
