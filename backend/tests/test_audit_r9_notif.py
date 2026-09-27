"""Runda 9 audytu — powiadomienia (NOTIF): testy bez bazy.

R9-N2-1  wyciszony „Czat” odpada w SQL, kolejka ma keyset.
R9-N2-2  osoby z otwartym gniazdem nie dostają maila; stempel co kilka minut.
R9-N2-3  błąd bazy przy sprawdzaniu tokenu nie osieroca gniazda.
R9-N2-5  zdarzenie WS wychodzi po commicie, wycofany wiersz — nigdy.
R9-N2-8  menedżer gniazd iteruje po kopiach.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from sqlalchemy import Column, Integer, create_engine
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session, declarative_base

from app.api import ws
from app.services import notification_ws_after_commit as after_commit
from app.services.notification_delivery import DeliveryPolicy
from app.tasks import chat_email_fallback as fallback


def _policy() -> DeliveryPolicy:
    return DeliveryPolicy.from_value(
        {
            "enabled": True,
            "send_not_before": "2026-09-22T12:00:00+00:00",
            "types": {
                "chat_unread": {
                    "email_enabled": True,
                    "send_not_before": "2026-09-22T12:30:00+00:00",
                }
            },
        }
    )


def _compiled(query):
    return query.compile(dialect=postgresql.dialect())


# ── R9-N2-1 / R9-N2-2: kolejka maili czatu ────────────────────────────────────


def test_muted_chat_is_filtered_in_sql_not_in_python() -> None:
    compiled = _compiled(
        fallback.pending_candidate_query(datetime.now(timezone.utc), _policy())
    )
    sql = str(compiled)
    assert "users.muted_notification_categories ? " in sql
    assert "chat" in compiled.params.values()
    # Wzmianka (kategoria obowiązkowa) nie jest objęta wyciszeniem.
    assert "notifications.notification_type != " in sql


def test_queue_is_keyset_ordered_and_can_exclude_online_users() -> None:
    after = (datetime(2026, 9, 1, tzinfo=timezone.utc), 42)
    compiled = _compiled(
        fallback.pending_candidate_query(
            datetime.now(timezone.utc),
            _policy(),
            exclude_user_ids=[7, 3, 7],
            after=after,
        )
    )
    sql = str(compiled)
    assert "ORDER BY notifications.created_at ASC, notifications.id ASC" in sql
    assert "users.id NOT IN" in sql
    assert [3, 7] in compiled.params.values()
    assert "(notifications.created_at, notifications.id) > " in sql
    assert 42 in compiled.params.values()


def test_online_user_ids_come_from_the_socket_manager(monkeypatch) -> None:
    monkeypatch.setattr(ws.manager, "_connections", {11: [object()], 12: [object()]})
    assert fallback._online_user_ids() == frozenset({11, 12})


async def test_last_seen_is_refreshed_at_most_every_few_minutes(monkeypatch) -> None:
    stamp = AsyncMock()
    monkeypatch.setattr(ws, "_stamp_last_seen", stamp)
    now = asyncio.get_running_loop().time()

    assert await ws._refresh_last_seen(5, now) == now
    stamp.assert_not_awaited()

    stale = now - ws.LAST_SEEN_REFRESH_SECONDS - 1
    refreshed = await ws._refresh_last_seen(5, stale)
    stamp.assert_awaited_once_with(5)
    assert refreshed > stale
    # Próg musi być wyraźnie krótszy niż „offline” fallbacku mailowego.
    assert ws.LAST_SEEN_REFRESH_SECONDS < fallback.OFFLINE_THRESHOLD_MIN * 60


# ── R9-N2-3 / R9-N2-8: menedżer gniazd ───────────────────────────────────────


def _socket() -> MagicMock:
    socket = MagicMock()
    socket.send_json = AsyncMock()
    socket.close = AsyncMock()
    return socket


async def test_db_error_during_token_check_does_not_orphan_the_socket(
    monkeypatch,
) -> None:
    manager = ws.ConnectionManager()
    socket = _socket()
    manager._connections[9001] = [socket]
    manager._auth_tokens[socket] = "token"
    monkeypatch.setattr(
        ws, "_authenticate_ws_token", AsyncMock(side_effect=OSError("db down"))
    )

    await manager.notify_user(9001, {"type": "notification", "data": {}})

    # Gniazdo zostaje w menedżerze (następne zdarzenie spróbuje znowu), a nie
    # znika bez zamknięcia, zostawiając klienta z martwym połączeniem.
    assert manager._connections[9001] == [socket]
    socket.close.assert_not_awaited()


async def test_failed_send_closes_the_socket_before_dropping_it(monkeypatch) -> None:
    monkeypatch.setattr(ws, "_stamp_last_seen", AsyncMock())
    manager = ws.ConnectionManager()
    socket = _socket()
    socket.send_json = AsyncMock(side_effect=RuntimeError("broken pipe"))
    manager._connections[9002] = [socket]

    await manager.notify_user(9002, {"type": "ping"})

    assert 9002 not in manager._connections
    socket.close.assert_awaited_once()
    assert socket.close.await_args.kwargs["code"] == 1011


async def test_notify_user_iterates_a_copy_of_the_connection_list(
    monkeypatch,
) -> None:
    monkeypatch.setattr(ws, "_stamp_last_seen", AsyncMock())
    manager = ws.ConnectionManager()
    first, second = _socket(), _socket()
    manager._connections[9003] = [first, second]

    async def first_send(_event):
        # Inne zadanie rozłącza pierwszą kartę w trakcie wysyłki.
        manager._connections[9003].remove(first)

    first.send_json = AsyncMock(side_effect=first_send)

    await manager.notify_user(9003, {"type": "ping"})

    second.send_json.assert_awaited_once()


async def test_presence_broadcast_survives_viewer_list_change_mid_send() -> None:
    manager = ws.ConnectionManager()
    key = ws._make_key("candidate", 5)
    a, b = _socket(), _socket()
    manager._viewers[key] = {1: {a}, 2: {b}}

    async def leave(_event):
        manager._viewers[key].pop(2, None)
        manager._viewers[key].pop(1, None)

    a.send_json = AsyncMock(side_effect=leave)
    b.send_json = AsyncMock(side_effect=leave)

    # Do rundy 9: RuntimeError „dictionary changed size during iteration”.
    await manager._broadcast_update(key)


# ── R9-N2-5: wypchnięcie po commicie ─────────────────────────────────────────

_Base = declarative_base()


class _Row(_Base):
    __tablename__ = "r9_notif_rows"
    id = Column(Integer, primary_key=True)


class _AsyncLike:
    def __init__(self, sync_session: Session) -> None:
        self.sync_session = sync_session


async def _drain() -> None:
    for _ in range(5):
        await asyncio.sleep(0)


async def test_ws_event_is_sent_only_after_commit_and_only_for_kept_rows(
    monkeypatch,
) -> None:
    pushed: list[tuple[int, dict]] = []

    async def fake_notify(user_id, payload):
        pushed.append((user_id, payload))

    monkeypatch.setattr(ws, "notify_user", fake_notify)
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        db = _AsyncLike(session)
        kept = _Row(id=1)
        session.add(kept)
        session.flush()
        assert after_commit.queue_ws_notification(
            db, user_id=1, event_payload={"n": 1}, row=kept
        )

        savepoint = session.begin_nested()
        dropped = _Row(id=2)
        session.add(dropped)
        session.flush()
        after_commit.queue_ws_notification(
            db, user_id=2, event_payload={"n": 2}, row=dropped
        )
        savepoint.rollback()

        await _drain()
        assert pushed == []  # nic przed commitem

        session.commit()
        await _drain()

    assert pushed == [(1, {"n": 1})]


async def test_outer_rollback_discards_queued_events(monkeypatch) -> None:
    pushed: list = []
    monkeypatch.setattr(ws, "notify_user", AsyncMock(side_effect=pushed.append))
    engine = create_engine("sqlite://")
    _Base.metadata.create_all(engine)
    with Session(engine) as session:
        row = _Row(id=3)
        session.add(row)
        session.flush()
        after_commit.queue_ws_notification(
            _AsyncLike(session), user_id=3, event_payload={}, row=row
        )
        session.rollback()
        session.commit()
        await _drain()
    assert pushed == []


def test_fake_session_falls_back_to_immediate_push() -> None:
    assert (
        after_commit.queue_ws_notification(
            MagicMock(spec=[]), user_id=1, event_payload={}, row=object()
        )
        is False
    )
