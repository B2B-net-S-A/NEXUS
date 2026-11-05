"""Odrzucony refresh token: właściciel skrzynki ma dostać baner „Połącz ponownie”.

05.11.2026, produkcja: Microsoft odrzucił refresh token jednej skrzynki
(`invalid_grant`). `GraphClient` wyłączał połączenie ze statusem `error`,
a `GET /api/microsoft365/connection` przy wyłączonym wierszu z takim statusem
oddawał samo `connected=false`. Karta w Ustawieniach mówiła „Niepołączony” bez
wyjaśnienia, więc poczta i kalendarz stały przez 9 dni, a jedynym śladem był
`checks.m365 = degraded`.

Testy bez bazy: sesja-atrapa jak w `test_m365_sync_cursor_on_errors.py`.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api import microsoft365 as api_mod
from app.models.m365 import M365SyncStatus
from app.services.m365 import graph_client as graph_mod
from app.services.m365 import sync as sync_mod
from app.services.m365.access import CANDIDATE_SCOPE
from app.services.m365.connection_status import mark_reconnect_required
from app.services.m365.error_codes import classify_m365_error
from app.services.m365.oauth import M365ReauthRequired

pytestmark = pytest.mark.asyncio

_REJECTED = "Microsoft OAuth error: invalid_grant: AADSTS135010"


class _FakeDB:
    def __init__(self) -> None:
        self.commits = 0

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        pass

    async def refresh(self, instance) -> None:
        pass


def _conn(**overrides) -> SimpleNamespace:
    values = {
        "id": 1,
        "user_id": 1,
        "mailbox_upn": "skrzynka@example.com",
        "access_token_ct": "ct-access",
        "refresh_token_ct": "ct-refresh",
        "delta_token_messages": None,
        "delta_token_events": None,
        "is_active": True,
        "last_sync_status": M365SyncStatus.idle,
        "last_sync_at": None,
        "synced_through": None,
        "backfill_completed_at": None,
        "last_error": None,
    }
    return SimpleNamespace(**{**values, **overrides})


# ── GraphClient: refresh odrzucony przez Microsoft ───────────────────────────


async def test_rejected_refresh_token_marks_reconnect_required(monkeypatch):
    async def _reject(_refresh_token):
        raise M365ReauthRequired(_REJECTED)

    monkeypatch.setattr(graph_mod.m365_oauth, "refresh_tokens", _reject)
    conn = _conn()
    db = _FakeDB()
    client = graph_mod.GraphClient.__new__(graph_mod.GraphClient)
    client._conn = conn
    client._db = db
    client._refresh_token = "stary-token"

    with pytest.raises(M365ReauthRequired):
        await client._refresh_and_persist()

    assert conn.is_active is False
    assert conn.last_sync_status == M365SyncStatus.reconnect_required
    assert classify_m365_error(conn.last_error) == "reauth_required"
    assert db.commits >= 1


# ── Przebieg synchronizacji nie nadpisuje tego stanu statusem `error` ────────


class _FakeGraphClient:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self) -> "_FakeGraphClient":
        return self

    async def __aexit__(self, *_exc_info) -> None:
        pass


async def _no_events(*_args, **_kwargs) -> None:
    return None


async def test_sync_pass_keeps_reconnect_required_when_refresh_is_rejected(monkeypatch):
    db = _FakeDB()
    conn = _conn()

    async def _rejected(_db, _gc, _conn, _result, **_kwargs):
        await mark_reconnect_required(_db, _conn, repr(M365ReauthRequired(_REJECTED)))
        raise M365ReauthRequired(_REJECTED)

    monkeypatch.setattr(sync_mod, "GraphClient", _FakeGraphClient)
    monkeypatch.setattr(sync_mod, "_sync_messages", _rejected)

    result = await sync_mod._sync_connection_locked(
        db, conn, sync_mod.SyncResult(connection_id=conn.id), CANDIDATE_SCOPE
    )

    assert conn.is_active is False
    assert conn.last_sync_status == M365SyncStatus.reconnect_required
    assert classify_m365_error(conn.last_error) == "reauth_required"
    assert result.errors == 1


async def test_rejection_swallowed_per_message_does_not_end_as_import_error(
    monkeypatch,
):
    """Pętla per wiadomość łapie każdy wyjątek, więc odrzucony refresh przy
    pobieraniu załącznika kończy się samym `result.errors += 1`."""
    db = _FakeDB()
    conn = _conn()

    async def _swallowed(_db, _gc, _conn, _result, **_kwargs):
        await mark_reconnect_required(_db, _conn, repr(M365ReauthRequired(_REJECTED)))
        _result.errors += 1
        _result.error_samples.append("msg: M365ReauthRequired")

    monkeypatch.setattr(sync_mod, "GraphClient", _FakeGraphClient)
    monkeypatch.setattr(sync_mod, "_sync_messages", _swallowed)
    monkeypatch.setattr(sync_mod, "_sync_events", _no_events)

    await sync_mod._sync_connection_locked(
        db, conn, sync_mod.SyncResult(connection_id=conn.id), CANDIDATE_SCOPE
    )

    assert conn.is_active is False
    assert conn.last_sync_status == M365SyncStatus.reconnect_required
    assert classify_m365_error(conn.last_error) == "reauth_required"


# ── Stan połączenia widziany przez kartę w Ustawieniach ──────────────────────


async def _connection_status(monkeypatch, conn):
    async def _get(_db, _user_id):
        return conn

    monkeypatch.setattr(api_mod, "_get_connection_for_user", _get)
    monkeypatch.setattr(
        api_mod,
        "mailbox_scope",
        lambda _user: SimpleNamespace(candidates=True, sales=False),
    )
    return await api_mod.get_connection(
        current_user=SimpleNamespace(id=1),
        response=SimpleNamespace(headers={}),
        db=_FakeDB(),
    )


@pytest.mark.parametrize(
    "status, last_error",
    [
        # Wiersz zapisany przed poprawką: bez zapisu w bazie też dostaje baner.
        (M365SyncStatus.error, f"M365ReauthRequired('{_REJECTED}')"),
        (M365SyncStatus.reconnect_required, f"M365ReauthRequired('{_REJECTED}')"),
        (M365SyncStatus.error, "token_cipher_unreadable_user_must_reconnect"),
        (
            M365SyncStatus.error,
            "Delta cursor for Inbox invalidated 4× in 24h — manual intervention required.",
        ),
    ],
)
async def test_disabled_connection_asks_owner_to_reconnect(
    monkeypatch, status, last_error
):
    conn = _conn(is_active=False, last_sync_status=status, last_error=last_error)

    body = await _connection_status(monkeypatch, conn)

    assert body.connected is False
    assert body.requires_reconnect is True
    assert body.mailbox_upn == "skrzynka@example.com"


async def test_active_connection_with_error_does_not_ask_to_reconnect(monkeypatch):
    conn = _conn(last_sync_status=M365SyncStatus.error, last_error="timeout after 480s")

    body = await _connection_status(monkeypatch, conn)

    assert body.connected is True
    assert body.requires_reconnect is False
