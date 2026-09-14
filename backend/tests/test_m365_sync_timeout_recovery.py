"""P1-M365-01 — a transient timeout must NOT permanently strand a connection.

Regression guard: ``_FATAL_ERROR_MARKERS`` used to include ``"timeout"``, so the
first network/Graph timeout wrote ``last_error="timeout ..."`` and the sync loop
then filtered that connection out of every subsequent tick FOREVER — while the
health endpoint still reported m365 healthy. A transient flake became a silent
permanent outage that only a manual reconnect could clear.

Timeouts and exhausted Graph 429/503 retries are transient. A connection, once
older than ``_ERROR_BACKOFF_SECONDS``, is re-selected by ``_tick`` on the normal
~30-min retry cadence and auto-recovers. Genuinely non-recoverable markers
(reauth required) still drop the connection.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.core.security import hash_password
from app.models.m365 import M365Connection, M365SyncStatus
from app.models.user import User, UserRole
from app.tasks import microsoft365_sync

pytestmark = pytest.mark.asyncio


async def _make_user_and_connection(db, *, last_error: str) -> tuple[int, int]:
    """Create a fresh user + one M365 connection (user_id is UNIQUE — 1:1)."""
    unique = uuid.uuid4().hex[:10]
    user = User(
        email=f"m365-timeout-{unique}@example.com",
        password_hash=hash_password(f"T3st_{unique}!PassX"),
        name="M365 Timeout Test",
        role=UserRole.admin,
        is_active=True,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Errored 40 min ago → past the 30-min _ERROR_BACKOFF_SECONDS, so the SQL
    # WHERE re-admits it; whether it survives is decided by the fatal-marker
    # Python filter under test.
    errored_at = datetime.now(timezone.utc) - timedelta(minutes=40)
    conn = M365Connection(
        user_id=user.id,
        tenant_id="test-tenant",
        mailbox_upn=f"m365-{unique}@example.com",
        access_token_ct="ct-access",
        refresh_token_ct="ct-refresh",
        expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
        is_active=True,
        last_sync_status=M365SyncStatus.error,
        last_sync_at=errored_at,
        last_error=last_error,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    return user.id, conn.id


@pytest_asyncio.fixture(
    params=(
        "timeout after 480s",
        "GraphRequestError(\"Graph 503: 'retry_after cap exceeded (4x)'\")",
        "GraphRequestError(\"Graph 429: 'retry_after cap exceeded (4x)'\")",
    )
)
async def seeded_connections(request):
    """Due transient error, recent transient error, and reauth control.

    Each connection needs its own user — ``m365_connections.user_id`` is UNIQUE.
    """
    async with AsyncSessionLocal() as db:
        timeout_user_id, timeout_id = await _make_user_and_connection(
            db, last_error=request.param
        )
        reauth_user_id, reauth_id = await _make_user_and_connection(
            db, last_error="M365ReauthRequired: refresh token expired"
        )
        recent_user_id, recent_id = await _make_user_and_connection(
            db, last_error=request.param
        )
        recent = await db.get(M365Connection, recent_id)
        recent.last_sync_at = datetime.now(timezone.utc) - timedelta(minutes=5)
        await db.commit()

    yield {"timeout_id": timeout_id, "reauth_id": reauth_id, "recent_id": recent_id}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(M365Connection).where(
                M365Connection.id.in_([timeout_id, reauth_id, recent_id])
            )
        )
        await db.execute(
            delete(User).where(
                User.id.in_([timeout_user_id, reauth_user_id, recent_user_id])
            )
        )
        await db.commit()


async def test_timed_out_connection_is_reselected_not_dropped(
    seeded_connections: dict, monkeypatch
) -> None:
    """`_tick` must hand the timed-out connection to `sync_connection` again."""
    synced_ids: list[int] = []

    async def _fake_sync(db, conn) -> None:
        synced_ids.append(conn.id)
        if conn.id == seeded_connections["timeout_id"]:
            conn.last_sync_status = M365SyncStatus.idle
            conn.last_sync_at = datetime.now(timezone.utc)
            conn.last_error = None
            await db.commit()

    monkeypatch.setattr(microsoft365_sync, "sync_connection", _fake_sync)
    # Keep the per-connection stagger from slowing the test.
    monkeypatch.setattr(microsoft365_sync.asyncio, "sleep", AsyncMock())

    await microsoft365_sync._tick(interval=300)

    timeout_id = seeded_connections["timeout_id"]
    reauth_id = seeded_connections["reauth_id"]

    # The timeout is transient — it must be retried (auto-recovery).
    assert timeout_id in synced_ids, (
        "a connection whose last_error is a timeout must be re-selected once the "
        "error backoff has elapsed, not permanently skipped"
    )
    # The reauth marker is genuinely fatal — it must still be filtered out.
    assert reauth_id not in synced_ids, (
        "M365ReauthRequired is fatal and must stay in _FATAL_ERROR_MARKERS"
    )
    assert seeded_connections["recent_id"] not in synced_ids, (
        "preserve 30-minute backoff"
    )
    await microsoft365_sync._tick(interval=300)
    assert synced_ids.count(timeout_id) == 1, (
        "a recovered connection waits for its next interval"
    )


@pytest.mark.parametrize("status", [429, 503])
async def test_throttle_recovery_without_database(monkeypatch, status):
    """Exercise the real scheduler with due rows, preserving the reauth gate."""
    transient = SimpleNamespace(
        id=1,
        is_active=True,
        last_error=f"GraphRequestError(\"Graph {status}: 'retry_after cap exceeded (4x)'\")",
    )
    reauth = SimpleNamespace(
        id=2, is_active=True, last_error="M365ReauthRequired: refresh token expired"
    )
    db = AsyncMock()
    rows = MagicMock()
    rows.scalars.return_value.all.return_value = [transient, reauth]
    db.execute.return_value = rows
    db.get.return_value = transient
    context = MagicMock()
    context.__aenter__ = AsyncMock(return_value=db)
    context.__aexit__ = AsyncMock(return_value=False)
    monkeypatch.setattr(microsoft365_sync, "AsyncSessionLocal", lambda: context)
    monkeypatch.setattr(
        microsoft365_sync, "connection_owner_is_eligible", AsyncMock(return_value=True)
    )
    sync = AsyncMock()
    monkeypatch.setattr(microsoft365_sync, "sync_connection", sync)
    monkeypatch.setattr(microsoft365_sync.asyncio, "sleep", AsyncMock())
    await microsoft365_sync._tick(interval=300)
    sync.assert_awaited_once_with(db, transient)


async def test_timeout_no_longer_a_fatal_marker() -> None:
    """Direct guard on the constant so the regression can't silently return."""
    markers = microsoft365_sync._FATAL_ERROR_MARKERS
    assert not any("timeout" in m.lower() for m in markers), (
        "'timeout' must not be a fatal marker — it strands transient flakes"
    )
    # The genuinely-fatal markers stay.
    assert "M365ReauthRequired" in markers
