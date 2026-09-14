"""INT-01 (audyt integracji, 14.09.2026) — kursor delty M365 nie przesuwa się
po przebiegu z błędami, a przebieg z błędami nie udaje `idle`.

Regresja była CICHA i kosztowała dane. `_sync_messages_for_folder` łapie wyjątek
per wiadomość (`result.errors += 1`) i padnięty commit strony (rollback,
`result.errors += 1`), po czym — bez patrzenia na `result.errors` — zapisywał
`@odata.deltaLink`. Graph traktuje odebrany deltaLink jako potwierdzenie
wchłonięcia całego okna, więc wiadomości, które przepadły, nie wracały już
nigdy. Na dokładkę `_sync_connection_locked` stemplował `last_sync_status =
idle` bezwarunkowo, więc bieg z pięćdziesięcioma błędami wyglądał dla sondy
`checks.m365` (czyta `last_sync_status`) jak zdrowy.

Testy sterują Graph atrapą stron (jak `test_m365_page_commit_resilience.py`)
i sesją-atrapą (jak `test_m365_sync_single_flight.py`); dane są syntetyczne.
Każdy scenariusz z błędem pada na kodzie sprzed poprawki (sprawdzone mutacją).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.models.m365 import M365SyncStatus
from app.services.m365 import sync as sync_mod

pytestmark = pytest.mark.asyncio

_OLD_INBOX = "https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta?$deltatoken=old-inbox"
_OLD_SENT = "https://graph.microsoft.com/v1.0/me/mailFolders/sentitems/messages/delta?$deltatoken=old-sent"
_OLD_EVENTS = (
    "https://graph.microsoft.com/v1.0/me/calendarView/delta?$deltatoken=old-events"
)
_NEW_LINK = "https://graph.microsoft.com/v1.0/me/messages/delta?$deltatoken=new-window"


class _FakeGraphClient:
    """Oddaje z góry zadane strony; ostatnia niesie `@odata.deltaLink`."""

    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    async def paginate(self, url, params=None):  # noqa: ANN001 - atrapa
        for page in self._pages:
            yield page


class _FakeDB:
    """Sesja-atrapa: `fail_commit_on` = numer commitu, który ma paść (0 = żaden)."""

    def __init__(self, fail_commit_on: int = 0) -> None:
        self.fail_commit_on = fail_commit_on
        self.commits = 0
        self.rollbacks = 0

    async def commit(self) -> None:
        self.commits += 1
        if self.commits == self.fail_commit_on:
            raise RuntimeError("current transaction is aborted")

    async def rollback(self) -> None:
        self.rollbacks += 1


def _conn() -> SimpleNamespace:
    return SimpleNamespace(
        id=1,
        user_id=1,
        delta_token_inbox=_OLD_INBOX,
        delta_token_sent=_OLD_SENT,
        delta_token_events=_OLD_EVENTS,
        delta_reset_count=0,
        delta_last_reset_at=None,
        backfill_completed_at=None,
        synced_through=None,
        is_active=True,
        last_sync_status=M365SyncStatus.idle,
        last_sync_at=None,
        last_error=None,
    )


def _three_pages() -> list[dict]:
    return [
        {"value": [{"id": "m-1"}, {"id": "m-2"}], "@odata.nextLink": "n1"},
        {"value": [{"id": "m-3"}, {"id": "m-4"}], "@odata.nextLink": "n2"},
        {"value": [{"id": "m-5"}], "@odata.deltaLink": _NEW_LINK},
    ]


def _upsert_failing_on(bad_ids: set[str]):
    async def _fake_upsert(db, gc, conn, msg, folder):  # noqa: ANN001 - atrapa
        if msg["id"] in bad_ids:
            raise RuntimeError(f"cannot ingest {msg['id']}")
        return SimpleNamespace(id=msg["id"])

    return _fake_upsert


async def _run_folder(
    db, conn, pages, *, folder="Inbox", cursor_attr="delta_token_inbox"
):
    result = sync_mod.SyncResult(connection_id=conn.id)
    await sync_mod._sync_messages_for_folder(
        db,
        _FakeGraphClient(pages),
        conn,
        result,
        folder=folder,
        cursor_attr=cursor_attr,
        is_backfill=False,
    )
    return result


# ── (a) błąd jednej wiadomości na stronie 2 z 3 ──────────────────────────────


async def test_message_error_on_middle_page_leaves_cursor_untouched(monkeypatch):
    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert_failing_on({"m-3"}))
    db = _FakeDB()
    conn = _conn()

    result = await _run_folder(db, conn, _three_pages())

    assert result.errors == 1
    assert any("msg:" in s for s in result.error_samples)
    # Reszta okna została wchłonięta — nie urywamy przebiegu na jednym mailu…
    assert result.messages_ingested == 4
    # …ale deltaLink NIE jest potwierdzany: Graph oddałby m-3 już nigdy.
    assert conn.delta_token_inbox == _OLD_INBOX, (
        "kursor przesunął się mimo błędu importu — utracona wiadomość nie wróci"
    )


# ── (b) padnięty commit strony ───────────────────────────────────────────────


async def test_failed_page_commit_leaves_cursor_untouched(monkeypatch):
    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert_failing_on(set()))
    db = _FakeDB(fail_commit_on=2)  # commit strony 2 z 3
    conn = _conn()

    result = await _run_folder(db, conn, _three_pages())

    assert result.errors == 1
    assert db.rollbacks == 1
    assert any("page-commit" in s for s in result.error_samples)
    assert conn.delta_token_inbox == _OLD_INBOX, (
        "kursor przesunął się mimo utraty całej strony maili"
    )


# ── (c) czysty przebieg ──────────────────────────────────────────────────────


async def test_clean_run_advances_cursor_to_last_delta_link(monkeypatch):
    """Kontrola negatywna: bez niej testy wyżej przechodziłyby też dla kodu,
    który nigdy nie zapisuje kursora."""
    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert_failing_on(set()))
    db = _FakeDB()
    conn = _conn()

    result = await _run_folder(db, conn, _three_pages())

    assert result.errors == 0
    assert result.messages_ingested == 5
    assert conn.delta_token_inbox == _NEW_LINK


# ── licznik jest per folder, nie per przebieg ────────────────────────────────


async def test_error_in_one_folder_does_not_block_the_other_folders_cursor(
    monkeypatch,
):
    """Inbox czysty, SentItems z błędem: Inbox idzie dalej, Sent zostaje.

    Licznik `result.errors` jest wspólny dla przebiegu, więc folder oceniany po
    wartości bezwzględnej cofałby też sąsiada, który przeszedł bez błędu."""
    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert_failing_on({"m-3"}))
    conn = _conn()
    result = sync_mod.SyncResult(connection_id=conn.id)
    db = _FakeDB()

    # Wspólny `result` dla obu folderów — jak w `_sync_messages`.
    await sync_mod._sync_messages_for_folder(
        db,
        _FakeGraphClient([{"value": [{"id": "s-1"}], "@odata.deltaLink": _NEW_LINK}]),
        conn,
        result,
        folder="Inbox",
        cursor_attr="delta_token_inbox",
        is_backfill=False,
    )
    await sync_mod._sync_messages_for_folder(
        db,
        _FakeGraphClient(_three_pages()),
        conn,
        result,
        folder="SentItems",
        cursor_attr="delta_token_sent",
        is_backfill=False,
    )

    assert result.errors == 1
    assert conn.delta_token_inbox == _NEW_LINK
    assert conn.delta_token_sent == _OLD_SENT


# ── (d) wydarzenia ───────────────────────────────────────────────────────────


async def _run_events(db, conn, pages):
    result = sync_mod.SyncResult(connection_id=conn.id)
    await sync_mod._sync_events(db, _FakeGraphClient(pages), conn, result)
    return result


def _event_pages() -> list[dict]:
    return [
        {"value": [{"id": "e-1"}, {"id": "e-2"}], "@odata.nextLink": "n1"},
        {"value": [{"id": "e-3"}], "@odata.deltaLink": _NEW_LINK},
    ]


def _upsert_event_failing_on(bad_ids: set[str]):
    async def _fake_upsert(db, conn, ev):  # noqa: ANN001 - atrapa
        if ev["id"] in bad_ids:
            raise RuntimeError(f"cannot ingest {ev['id']}")
        return True

    return _fake_upsert


async def test_event_error_leaves_events_cursor_untouched(monkeypatch):
    monkeypatch.setattr(sync_mod, "_upsert_event", _upsert_event_failing_on({"e-2"}))
    conn = _conn()

    result = await _run_events(_FakeDB(), conn, _event_pages())

    assert result.errors == 1
    assert result.events_ingested == 2
    assert conn.delta_token_events == _OLD_EVENTS, (
        "kursor wydarzeń przesunął się mimo błędu importu"
    )


async def test_clean_events_run_advances_events_cursor(monkeypatch):
    monkeypatch.setattr(sync_mod, "_upsert_event", _upsert_event_failing_on(set()))
    conn = _conn()

    result = await _run_events(_FakeDB(), conn, _event_pages())

    assert result.errors == 0
    assert conn.delta_token_events == _NEW_LINK


# ── status przebiegu: `error`, nie `idle` ────────────────────────────────────


class _NoopGraphClient:
    def __init__(self, conn, db):  # noqa: D107 — atrapa
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def _bare_sync_connection(monkeypatch):
    """`sync_connection` bez bazy, Graph i bramki uprawnień — jak w
    `test_m365_sync_single_flight.py`."""
    monkeypatch.setattr(sync_mod, "_sync_locks", {})

    async def _eligible(_db, _conn):
        return True

    monkeypatch.setattr(sync_mod, "connection_owner_is_eligible", _eligible)
    monkeypatch.setattr(sync_mod, "GraphClient", _NoopGraphClient)

    async def _noop_events(db, gc, conn, result):
        return None

    monkeypatch.setattr(sync_mod, "_sync_events", _noop_events)


async def test_run_with_import_errors_ends_in_error_status(
    _bare_sync_connection, monkeypatch
):
    async def _messages_with_errors(db, gc, conn, result):
        result.messages_ingested += 4
        result.errors += 3
        result.error_samples.append("msg: RuntimeError('cannot ingest m-3')")

    monkeypatch.setattr(sync_mod, "_sync_messages", _messages_with_errors)
    conn = _conn()

    result = await sync_mod.sync_connection(_FakeDB(), conn)

    assert result.errors == 3
    assert conn.last_sync_status == M365SyncStatus.error, (
        "bieg z błędami zgłosił `idle` — sonda checks.m365 go nie zobaczy"
    )
    assert conn.last_error
    assert "3 błędów importu" in conn.last_error
    assert "kursor" in conn.last_error
    assert "cannot ingest m-3" in conn.last_error
    assert conn.last_sync_at is not None


async def test_clean_run_ends_in_idle_status(_bare_sync_connection, monkeypatch):
    async def _clean_messages(db, gc, conn, result):
        result.messages_ingested += 4

    monkeypatch.setattr(sync_mod, "_sync_messages", _clean_messages)
    conn = _conn()

    await sync_mod.sync_connection(_FakeDB(), conn)

    assert conn.last_sync_status == M365SyncStatus.idle
    assert conn.last_error is None


async def test_error_status_survives_the_whole_path_from_a_bad_page(
    _bare_sync_connection, monkeypatch
):
    """Bez atrapy `_sync_messages`: prawdziwa pętla folderów + atrapa Graph.
    Sprawdza, że kursor i status idą razem — Inbox z błędem zostaje na starym
    linku, Sent (czysty) idzie dalej, a przebieg kończy się `error`."""
    monkeypatch.setattr(sync_mod, "_upsert_message", _upsert_failing_on({"m-3"}))

    class _Graph(_NoopGraphClient):
        async def paginate(self, url, params=None):  # noqa: ANN001 - atrapa
            pages = (
                _three_pages()
                if "Inbox" in url
                else [{"value": [{"id": "s-1"}], "@odata.deltaLink": _NEW_LINK}]
            )
            for page in pages:
                yield page

    monkeypatch.setattr(sync_mod, "GraphClient", _Graph)
    conn = _conn()
    # Kursory to prawdziwe linki delta → `_sync_messages_for_folder` użyje ich
    # jako URL, po czym `paginate` rozpozna folder po nazwie w linku.
    conn.delta_token_inbox = "https://graph.microsoft.com/v1.0/me/mailFolders/Inbox/messages/delta?$deltatoken=old-inbox"

    result = await sync_mod.sync_connection(_FakeDB(), conn)

    assert result.errors == 1
    assert conn.delta_token_inbox.endswith("$deltatoken=old-inbox")
    assert conn.delta_token_sent == _NEW_LINK
    assert conn.last_sync_status == M365SyncStatus.error
