"""P1-M365-01 — a transient timeout must NOT permanently strand a connection.

Regression guard: ``_FATAL_ERROR_MARKERS`` used to include ``"timeout"``, so the
first network/Graph timeout wrote ``last_error="timeout ..."`` and the sync loop
then filtered that connection out of every subsequent tick FOREVER — while the
health endpoint still reported m365 healthy. A transient flake became a silent
permanent outage that only a manual reconnect could clear.

The fix removes ``"timeout"`` from the fatal set so a timed-out connection, once
older than ``_ERROR_BACKOFF_SECONDS``, is re-selected by ``_tick`` on the normal
~30-min retry cadence and auto-recovers. Genuinely non-recoverable markers
(reauth required) still drop the connection.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

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


@pytest_asyncio.fixture
async def seeded_connections():
    """One timed-out connection + one reauth-required connection (control).

    Each connection needs its own user — ``m365_connections.user_id`` is UNIQUE.
    """
    async with AsyncSessionLocal() as db:
        timeout_user_id, timeout_id = await _make_user_and_connection(
            db, last_error="timeout after 480s"
        )
        reauth_user_id, reauth_id = await _make_user_and_connection(
            db, last_error="M365ReauthRequired: refresh token expired"
        )

    yield {"timeout_id": timeout_id, "reauth_id": reauth_id}

    async with AsyncSessionLocal() as db:
        await db.execute(
            delete(M365Connection).where(M365Connection.id.in_([timeout_id, reauth_id]))
        )
        await db.execute(
            delete(User).where(User.id.in_([timeout_user_id, reauth_user_id]))
        )
        await db.commit()


async def test_timed_out_connection_is_reselected_not_dropped(
    seeded_connections: dict, monkeypatch
) -> None:
    """`_tick` must hand the timed-out connection to `sync_connection` again."""
    synced_ids: list[int] = []

    async def _fake_sync(db, conn) -> None:
        synced_ids.append(conn.id)

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


async def test_timeout_no_longer_a_fatal_marker() -> None:
    """Direct guard on the constant so the regression can't silently return."""
    markers = microsoft365_sync._FATAL_ERROR_MARKERS
    assert not any("timeout" in m.lower() for m in markers), (
        "'timeout' must not be a fatal marker — it strands transient flakes"
    )
    # The genuinely-fatal markers stay.
    assert "M365ReauthRequired" in markers
