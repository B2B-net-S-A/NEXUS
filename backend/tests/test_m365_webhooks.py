"""Unit tests for the Graph push-webhook surface (Phase 7.3).

Three layers covered:

1. `app.services.m365.webhooks` — subscribe/renew/unsubscribe/list_due.
2. The replay-protection LRU + validation-handshake/dispatch logic in
   `app.api.microsoft365.webhooks` (called as a pure async function with
   stubbed Request + AsyncMock db).
3. The renewal-loop tick orchestration in
   `app.tasks.microsoft365_sync._renewal_tick` (verifies the loop groups
   subs by connection and skips inactive rows).

Same style as `test_m365_rematch.py` / `test_m365_sync_helpers.py`: no real
DB, no httpx — just SimpleNamespace stand-ins + AsyncMock for I/O. Keeps the
suite fast and CI-portable (Postgres-free).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api import microsoft365 as m365_api
from app.services.m365 import webhooks as svc
from app.services.m365.graph_client import GraphRequestError


# pytest-asyncio is configured with `asyncio_mode = auto` (pytest.ini), so
# async tests are detected automatically — no module-level marker needed.


# ── Shared fixtures ─────────────────────────────────────────────────────────


def _make_conn(
    *, conn_id: int = 1, user_id: int = 10, is_active: bool = True
) -> SimpleNamespace:
    return SimpleNamespace(
        id=conn_id,
        user_id=user_id,
        is_active=is_active,
    )


def _make_sub(
    *,
    sub_id: int = 100,
    conn_id: int = 1,
    user_id: int = 10,
    resource: str = "me/mailFolders('inbox')/messages",
    subscription_id: str = "graph-sub-abc",
    client_state: str = "shared-secret-xyz",
    expires_in_minutes: int = 5,
    renewal_failure_count: int = 0,
) -> SimpleNamespace:
    return SimpleNamespace(
        id=sub_id,
        m365_connection_id=conn_id,
        user_id=user_id,
        resource=resource,
        change_type="created,updated",
        subscription_id=subscription_id,
        notification_url="https://api.example.com/api/microsoft365/webhooks",
        client_state=client_state,
        expires_at=datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes),
        last_renewed_at=None,
        renewal_failure_count=renewal_failure_count,
        last_error=None,
    )


def _make_db_with_added() -> SimpleNamespace:
    """Db stub that records add()/delete()/flush()/commit() calls."""
    added: list[Any] = []
    deleted: list[Any] = []
    db = SimpleNamespace(
        add=lambda obj: added.append(obj),
        delete=AsyncMock(side_effect=lambda obj: deleted.append(obj)),
        flush=AsyncMock(),
        commit=AsyncMock(),
        added=added,
        deleted=deleted,
    )
    return db


# ── service.subscribe ───────────────────────────────────────────────────────


async def test_subscribe_persists_row_with_graph_response() -> None:
    """subscribe() POSTs to Graph, then creates a row with the returned id + expiry."""
    db = _make_db_with_added()
    conn = _make_conn()
    expires_iso = "2030-01-01T12:00:00Z"
    gc = SimpleNamespace(
        post=AsyncMock(
            return_value={"id": "graph-sub-XYZ", "expirationDateTime": expires_iso}
        )
    )

    row = await svc.subscribe(
        db,
        gc,
        conn,
        resource="me/events",
        change_type="created,updated,deleted",
    )

    # POST went out with the right shape.
    gc.post.assert_awaited_once()
    args, kwargs = gc.post.await_args
    assert args[0] == "/subscriptions"
    body = kwargs["json"]
    assert body["resource"] == "me/events"
    assert body["changeType"] == "created,updated,deleted"
    assert body["notificationUrl"].endswith("/api/microsoft365/webhooks")
    # client_state is a random secret of meaningful length.
    assert len(body["clientState"]) >= 32

    # Row was added with values from the response.
    assert row.subscription_id == "graph-sub-XYZ"
    assert row.client_state == body["clientState"]
    assert row.resource == "me/events"
    assert row.user_id == conn.user_id
    assert row.m365_connection_id == conn.id
    assert row.expires_at == datetime(2030, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert db.added == [row]
    db.flush.assert_awaited_once()
    # No commit — the caller owns the transaction.
    db.commit.assert_not_called()


async def test_subscribe_rejects_unexpected_graph_body() -> None:
    """Graph returning a body without `id` must surface as GraphRequestError."""
    db = _make_db_with_added()
    conn = _make_conn()
    gc = SimpleNamespace(post=AsyncMock(return_value={"error": {"code": "Forbidden"}}))

    with pytest.raises(GraphRequestError):
        await svc.subscribe(db, gc, conn, resource="me/events", change_type="created")
    # No row leaked.
    assert db.added == []


# ── service.renew ───────────────────────────────────────────────────────────


async def test_renew_success_updates_expiry_and_resets_failures() -> None:
    sub = _make_sub(renewal_failure_count=2, expires_in_minutes=-1)  # already expired
    db = _make_db_with_added()
    gc = SimpleNamespace(
        patch=AsyncMock(return_value={"expirationDateTime": "2030-06-01T08:00:00Z"})
    )

    ok = await svc.renew(db, gc, sub)

    assert ok is True
    gc.patch.assert_awaited_once()
    assert sub.expires_at == datetime(2030, 6, 1, 8, 0, 0, tzinfo=timezone.utc)
    assert sub.last_renewed_at is not None
    assert sub.last_renewed_at.tzinfo == timezone.utc
    assert sub.renewal_failure_count == 0
    assert sub.last_error is None


async def test_renew_failure_bumps_count_but_keeps_row(monkeypatch) -> None:
    """Single failure below threshold → row stays, counter bumps, last_error set."""
    monkeypatch.setattr(svc.settings, "M365_WEBHOOK_FAILURE_THRESHOLD", 3)
    sub = _make_sub(renewal_failure_count=0)
    db = _make_db_with_added()
    gc = SimpleNamespace(patch=AsyncMock(side_effect=GraphRequestError(500, "oops")))

    ok = await svc.renew(db, gc, sub)

    assert ok is False
    assert sub.renewal_failure_count == 1
    assert sub.last_error is not None and "oops" in sub.last_error
    db.delete.assert_not_called()


async def test_renew_failure_at_threshold_deletes_row(monkeypatch) -> None:
    """After enough failures the row is removed so the loop can re-subscribe."""
    monkeypatch.setattr(svc.settings, "M365_WEBHOOK_FAILURE_THRESHOLD", 3)
    sub = _make_sub(renewal_failure_count=2)  # one more failure crosses the line
    db = _make_db_with_added()
    gc = SimpleNamespace(patch=AsyncMock(side_effect=GraphRequestError(404, "gone")))

    ok = await svc.renew(db, gc, sub)

    assert ok is False
    assert sub.renewal_failure_count == 3
    db.delete.assert_awaited_once_with(sub)


async def test_renew_handles_empty_patch_body() -> None:
    """Graph occasionally returns 200 with no JSON body — fall back to requested time."""
    sub = _make_sub()
    db = _make_db_with_added()
    gc = SimpleNamespace(patch=AsyncMock(return_value=None))

    ok = await svc.renew(db, gc, sub)

    assert ok is True
    # We don't pin the exact value (depends on now()), but it must be in the
    # future and roughly inside the configured lifetime window.
    now = datetime.now(timezone.utc)
    assert sub.expires_at > now
    assert sub.expires_at <= now + timedelta(
        minutes=svc.settings.M365_WEBHOOK_LIFETIME_MINUTES + 1
    )


# ── service.unsubscribe ─────────────────────────────────────────────────────


async def test_unsubscribe_deletes_row_after_graph_delete() -> None:
    sub = _make_sub()
    db = _make_db_with_added()
    gc = SimpleNamespace(delete=AsyncMock(return_value=None))

    await svc.unsubscribe(db, gc, sub)

    gc.delete.assert_awaited_once_with(f"/subscriptions/{sub.subscription_id}")
    db.delete.assert_awaited_once_with(sub)
    db.flush.assert_awaited_once()


async def test_unsubscribe_swallows_404_and_still_drops_row() -> None:
    sub = _make_sub()
    db = _make_db_with_added()
    gc = SimpleNamespace(delete=AsyncMock(side_effect=GraphRequestError(404, "gone")))

    # No raise — Graph already lost track of it.
    await svc.unsubscribe(db, gc, sub)

    db.delete.assert_awaited_once_with(sub)


# ── service.auto_subscribe_after_connect ────────────────────────────────────


async def test_auto_subscribe_noop_when_feature_disabled(monkeypatch) -> None:
    """Auto-subscribe must skip work when the flag is off — and never touch the DB."""
    monkeypatch.setattr(svc.settings, "M365_WEBHOOKS_ENABLED", False)
    sessionmaker = MagicMock()
    monkeypatch.setattr(svc, "AsyncSessionLocal", sessionmaker)

    await svc.auto_subscribe_after_connect(connection_id=1)

    sessionmaker.assert_not_called()


# ── _replay_seen LRU ────────────────────────────────────────────────────────


def test_replay_seen_dedupes_within_ttl() -> None:
    m365_api._reset_replay_cache_for_tests()
    key = ("sub-1", "msg-A")
    assert m365_api._replay_seen(key) is False
    assert m365_api._replay_seen(key) is True
    # Different key — independent entry.
    assert m365_api._replay_seen(("sub-1", "msg-B")) is False


def test_replay_seen_evicts_when_over_cap(monkeypatch) -> None:
    """When the dict grows past the cap, oldest entries get popped (FIFO)."""
    m365_api._reset_replay_cache_for_tests()
    monkeypatch.setattr(m365_api, "_REPLAY_CACHE_MAX", 4)

    for i in range(6):
        m365_api._replay_seen((f"sub-{i}", "msg"))

    # Only the last 4 should remain.
    assert len(m365_api._replay_cache) == 4
    assert ("sub-0", "msg") not in m365_api._replay_cache
    assert ("sub-5", "msg") in m365_api._replay_cache


# ── endpoint: validation handshake ──────────────────────────────────────────


async def test_webhooks_validation_handshake_echoes_token() -> None:
    """Validation must succeed even when the feature flag is off — Graph cannot
    create the subscription otherwise."""
    request = MagicMock()
    response = await m365_api.webhooks(
        request=request,
        validationToken="opaque-graph-token-xyz",
        db=AsyncMock(),
    )

    assert response.status_code == 200
    # PlainTextResponse keeps the body in `.body` as bytes.
    assert response.body == b"opaque-graph-token-xyz"


async def test_webhooks_returns_503_when_disabled(monkeypatch) -> None:
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", False)
    request = MagicMock()

    with pytest.raises(m365_api.HTTPException) as exc:
        await m365_api.webhooks(request=request, validationToken=None, db=AsyncMock())
    assert exc.value.status_code == 503


# ── endpoint: notification dispatch ─────────────────────────────────────────


def _make_request_with_body(body: dict) -> MagicMock:
    """Stand-in for starlette Request whose .json() returns the given body."""
    request = MagicMock()
    request.json = AsyncMock(return_value=body)
    return request


async def test_webhooks_dispatches_sync_for_valid_notification(monkeypatch) -> None:
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()

    sub = _make_sub(client_state="secret-1")
    db = MagicMock()
    db.scalar = AsyncMock(return_value=sub)

    dispatched: list[int] = []

    async def fake_dispatch(connection_id: int) -> None:
        dispatched.append(connection_id)

    monkeypatch.setattr(m365_api, "_webhook_dispatch_sync", fake_dispatch)

    body = {
        "value": [
            {
                "subscriptionId": sub.subscription_id,
                "clientState": "secret-1",
                "resource": sub.resource,
                "resourceData": {"id": "msg-AAA"},
                "changeType": "created",
            }
        ]
    }

    response = await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )

    # Give the spawned task a tick to land.
    import asyncio

    await asyncio.sleep(0)

    assert response.status_code == 202
    assert dispatched == [sub.m365_connection_id]


async def test_webhooks_silently_skips_mismatched_client_state(monkeypatch) -> None:
    """A wrong client_state must NOT trigger sync — and must NOT 401 the whole
    request (multi-entry payloads might have one bad apple)."""
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()

    sub = _make_sub(client_state="correct-secret")
    db = MagicMock()
    db.scalar = AsyncMock(return_value=sub)

    dispatched: list[int] = []

    async def fake_dispatch(connection_id: int) -> None:
        dispatched.append(connection_id)

    monkeypatch.setattr(m365_api, "_webhook_dispatch_sync", fake_dispatch)

    body = {
        "value": [
            {
                "subscriptionId": sub.subscription_id,
                "clientState": "WRONG-secret",
                "resource": sub.resource,
                "resourceData": {"id": "msg-BBB"},
                "changeType": "created",
            }
        ]
    }

    response = await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )

    assert response.status_code == 202
    assert dispatched == []


async def test_webhooks_replay_protection(monkeypatch) -> None:
    """Same (subscriptionId, resourceData.id) twice → second is silently ignored."""
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()

    sub = _make_sub(client_state="secret-1")
    db = MagicMock()
    db.scalar = AsyncMock(return_value=sub)

    dispatched: list[int] = []

    async def fake_dispatch(connection_id: int) -> None:
        dispatched.append(connection_id)

    monkeypatch.setattr(m365_api, "_webhook_dispatch_sync", fake_dispatch)

    body = {
        "value": [
            {
                "subscriptionId": sub.subscription_id,
                "clientState": "secret-1",
                "resource": sub.resource,
                "resourceData": {"id": "msg-CCC"},
                "changeType": "created",
            }
        ]
    }
    import asyncio

    # First delivery — dispatched.
    await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )
    await asyncio.sleep(0)
    assert dispatched == [sub.m365_connection_id]

    # Second delivery with the same body — skipped at replay layer.
    await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )
    await asyncio.sleep(0)
    assert dispatched == [sub.m365_connection_id]  # unchanged


async def test_webhooks_ignores_unknown_subscription(monkeypatch) -> None:
    """Inbound for a subscription_id we no longer track → 202 without dispatch."""
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()

    db = MagicMock()
    db.scalar = AsyncMock(return_value=None)  # not found

    dispatched: list[int] = []

    async def fake_dispatch(connection_id: int) -> None:
        dispatched.append(connection_id)

    monkeypatch.setattr(m365_api, "_webhook_dispatch_sync", fake_dispatch)

    body = {
        "value": [
            {
                "subscriptionId": "ghost-sub",
                "clientState": "anything",
                "resource": "me/events",
                "resourceData": {"id": "ev-1"},
                "changeType": "updated",
            }
        ]
    }

    response = await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )

    assert response.status_code == 202
    assert dispatched == []


async def test_webhooks_dedupes_dispatch_for_same_connection(monkeypatch) -> None:
    """Three subs for the same connection ticking together → ONE sync, not three."""
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()

    # All three subs share conn_id=1 (default), so a sync dispatch should fire
    # exactly once even though the payload has three entries.
    sub_inbox = _make_sub(
        sub_id=1, subscription_id="sub-inbox", client_state="s", resource="inbox"
    )
    sub_sent = _make_sub(
        sub_id=2, subscription_id="sub-sent", client_state="s", resource="sent"
    )
    sub_events = _make_sub(
        sub_id=3, subscription_id="sub-events", client_state="s", resource="events"
    )

    db = MagicMock()
    # Endpoint scalar()s the SELECT in the same order it iterates `value`.
    db.scalar = AsyncMock(side_effect=[sub_inbox, sub_sent, sub_events])

    dispatched: list[int] = []

    async def fake_dispatch(connection_id: int) -> None:
        dispatched.append(connection_id)

    monkeypatch.setattr(m365_api, "_webhook_dispatch_sync", fake_dispatch)

    body = {
        "value": [
            {
                "subscriptionId": sub.subscription_id,
                "clientState": "s",
                "resource": sub.resource,
                "resourceData": {"id": f"r-{sub.subscription_id}"},
                "changeType": "created",
            }
            for sub in (sub_inbox, sub_sent, sub_events)
        ]
    }
    import asyncio

    await m365_api.webhooks(
        request=_make_request_with_body(body), validationToken=None, db=db
    )
    await asyncio.sleep(0)

    assert dispatched == [1]  # only one dispatch, all three subs share conn_id=1


async def test_webhooks_handles_empty_or_bad_body(monkeypatch) -> None:
    """No `value` key / non-dict body → 202 no-op (don't trip Graph backoff)."""
    monkeypatch.setattr(m365_api.settings, "M365_WEBHOOKS_ENABLED", True)
    m365_api._reset_replay_cache_for_tests()
    db = MagicMock()

    # Empty value list.
    resp = await m365_api.webhooks(
        request=_make_request_with_body({"value": []}),
        validationToken=None,
        db=db,
    )
    assert resp.status_code == 202

    # Non-dict body (Graph health pings sometimes send weird payloads).
    resp = await m365_api.webhooks(
        request=_make_request_with_body([]), validationToken=None, db=db
    )
    assert resp.status_code == 202


# ── service.list_due_for_renewal ────────────────────────────────────────────


async def test_list_due_for_renewal_filters_by_window() -> None:
    """The compiled SELECT must filter expires_at <= now+window."""
    db = SimpleNamespace(execute=AsyncMock())
    db.execute.return_value = SimpleNamespace(
        scalars=lambda: SimpleNamespace(all=lambda: [])
    )

    await svc.list_due_for_renewal(db, window_minutes=15)

    db.execute.assert_awaited_once()
    stmt = db.execute.await_args.args[0]
    sql = str(stmt.compile(compile_kwargs={"literal_binds": False}))
    assert "graph_subscriptions.expires_at <=" in sql
    assert "ORDER BY graph_subscriptions.expires_at" in sql
