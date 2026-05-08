"""Background loop that syncs every active M365 connection.

Same shape as `app/tasks/triggers_loop.py`:
- Grace period at startup so the rest of the app finishes bootstrap.
- Infinite while True that opens fresh DB sessions per iteration.
- Per-connection failures are logged + recorded on the row; the loop never dies.
- CancelledError propagates so lifespan shutdown works cleanly.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.encryption import TokenCipherNotConfigured
from app.models.m365 import M365Connection, M365SyncStatus
from app.services.m365 import sync_connection

logger = logging.getLogger(__name__)

# Fatal-error markers → skip that connection until user manually reconnects.
# These indicate the sync path itself is broken (not transient Graph flakes).
_FATAL_ERROR_MARKERS = ("timeout", "retry_after cap", "M365ReauthRequired")
# Backoff for connections whose last attempt errored — don't hammer them
# every 5 min. Artur can force with POST /api/microsoft365/sync/trigger.
_ERROR_BACKOFF_SECONDS = 30 * 60  # 30 min


async def microsoft365_sync_loop() -> None:
    """Long-running task — iterates active connections on a schedule."""
    if not settings.M365_INTEGRATION_ENABLED:
        logger.info("m365 sync loop disabled by M365_INTEGRATION_ENABLED=false")
        return
    if not settings.M365_SYNC_LOOP_ENABLED:
        logger.info(
            "m365 sync loop off (M365_SYNC_LOOP_ENABLED=false). "
            "Router still registered — enable env var to resume background sync."
        )
        return

    interval = max(60, settings.M365_SYNC_INTERVAL_SECONDS)
    logger.info("microsoft365_sync_loop started: interval=%ds", interval)
    # Give the rest of the app a head start.
    await asyncio.sleep(45)

    while True:
        try:
            await _tick(interval)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("microsoft365_sync_loop iteration failed")
        await asyncio.sleep(interval)


async def _tick(interval: int) -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=interval)
    error_cutoff = now - timedelta(seconds=_ERROR_BACKOFF_SECONDS)
    async with AsyncSessionLocal() as db:
        # Pick connections where:
        #  - is_active=True
        #  - status is NOT 'error', OR the error is older than 30 min (backoff)
        #  - last_sync_at is NULL or older than the loop interval
        stmt = (
            select(M365Connection)
            .where(
                M365Connection.is_active.is_(True),
                or_(
                    M365Connection.last_sync_status != M365SyncStatus.error,
                    and_(
                        M365Connection.last_sync_status == M365SyncStatus.error,
                        M365Connection.last_sync_at < error_cutoff,
                    ),
                ),
                or_(
                    M365Connection.last_sync_at.is_(None),
                    M365Connection.last_sync_at < cutoff,
                ),
            )
            .order_by(M365Connection.last_sync_at.asc().nulls_first())
        )
        result = await db.execute(stmt)
        connections = list(result.scalars().all())
        # Skip connections whose last_error looks fatal — user must reconnect.
        connections = [
            c
            for c in connections
            if not (
                c.last_error and any(m in c.last_error for m in _FATAL_ERROR_MARKERS)
            )
        ]

    if not connections:
        return

    logger.info("m365 sync tick — %d connection(s) due", len(connections))
    for conn_id in [c.id for c in connections]:
        # Fresh session per connection so one failure doesn't poison subsequent ones.
        try:
            async with AsyncSessionLocal() as db:
                fresh = await db.get(M365Connection, conn_id)
                if fresh is None or not fresh.is_active:
                    continue
                await sync_connection(db, fresh)
        except asyncio.CancelledError:
            raise
        except TokenCipherNotConfigured:
            # Cipher key rotated or token row was encrypted with a different
            # key (most often: key was missing at first encrypt, then provisioned;
            # or rotated without re-running OAuth). Token is unrecoverable —
            # deactivate so the loop stops retrying every 300s and Sentry doesn't
            # get a flood of identical events. User must reconnect via UI to
            # set is_active=True again with a freshly encrypted token.
            async with AsyncSessionLocal() as db:
                fresh = await db.get(M365Connection, conn_id)
                if fresh is not None:
                    fresh.is_active = False
                    fresh.last_sync_status = M365SyncStatus.error
                    fresh.last_error = "token_cipher_unreadable_user_must_reconnect"
                    await db.commit()
            logger.warning(
                "m365 connection id=%s deactivated — token unreadable (cipher mismatch). "
                "User must reconnect via /microsoft365 in the UI.",
                conn_id,
            )
        except Exception:  # noqa: BLE001
            logger.exception("sync_connection failed for id=%s", conn_id)
        # Stagger calls so Graph rate limits don't kick in.
        await asyncio.sleep(2)
