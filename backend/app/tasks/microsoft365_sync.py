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

from sqlalchemy import or_, select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.m365 import M365Connection
from app.services.m365 import sync_connection

logger = logging.getLogger(__name__)


async def microsoft365_sync_loop() -> None:
    """Long-running task — iterates active connections on a schedule."""
    if not settings.M365_INTEGRATION_ENABLED:
        logger.info("m365 sync loop disabled by M365_INTEGRATION_ENABLED=false")
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
    async with AsyncSessionLocal() as db:
        stmt = (
            select(M365Connection)
            .where(
                M365Connection.is_active.is_(True),
                or_(
                    M365Connection.last_sync_at.is_(None),
                    M365Connection.last_sync_at < cutoff,
                ),
            )
            .order_by(M365Connection.last_sync_at.asc().nulls_first())
        )
        result = await db.execute(stmt)
        connections = list(result.scalars().all())

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
        except Exception:  # noqa: BLE001
            logger.exception("sync_connection failed for id=%s", conn_id)
        # Stagger calls so Graph rate limits don't kick in.
        await asyncio.sleep(2)
