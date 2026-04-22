"""Background loop that dispatches due rejection emails.

Same shape as `app/tasks/microsoft365_sync.py` and the other async loops:
- Grace period on startup so the rest of the app finishes bootstrap.
- Infinite `while True` that opens fresh DB sessions per iteration.
- Per-row failures are logged; the loop never dies.
- CancelledError propagates so lifespan shutdown works cleanly.

The loop reads up to N pending rows whose `scheduled_at <= now()`, then
dispatches each in its own fresh session so a single transaction failure
doesn't poison subsequent sends.

Idempotent against multi-replica deploys: `dispatch()` uses
`SELECT ... FOR UPDATE SKIP LOCKED` to avoid double-sends.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy import select

from app.core.database import AsyncSessionLocal
from app.models.rejection_email import (
    RejectionEmailStatus,
    ScheduledRejectionEmail,
)
from app.services.rejection_email_scheduler import dispatch

logger = logging.getLogger(__name__)


# How often to scan the queue. 30s gives us sub-minute dispatch latency
# without hammering the DB; the 15-minute delay window absorbs the rest.
TICK_INTERVAL_SECONDS = 30
BATCH_LIMIT = 20
GRACE_PERIOD_SECONDS = 20


async def rejection_email_loop() -> None:
    """Long-running task — dispatches due ScheduledRejectionEmail rows."""
    logger.info(
        "rejection_email_loop started: interval=%ds, batch=%d",
        TICK_INTERVAL_SECONDS,
        BATCH_LIMIT,
    )
    # Give lifespan startup a moment (migrations, connection pools).
    await asyncio.sleep(GRACE_PERIOD_SECONDS)

    while True:
        try:
            await _tick()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("rejection_email_loop iteration failed")
        await asyncio.sleep(TICK_INTERVAL_SECONDS)


async def _tick() -> None:
    """One pass: collect due ids, dispatch each in its own session."""
    async with AsyncSessionLocal() as db:
        due_ids = (
            await db.scalars(
                select(ScheduledRejectionEmail.id)
                .where(
                    ScheduledRejectionEmail.status == RejectionEmailStatus.pending,
                    ScheduledRejectionEmail.scheduled_at
                    <= datetime.now(timezone.utc),
                )
                .order_by(ScheduledRejectionEmail.scheduled_at.asc())
                .limit(BATCH_LIMIT)
            )
        ).all()

    if not due_ids:
        return

    logger.info("rejection_email_loop tick — %d due row(s)", len(due_ids))
    for row_id in due_ids:
        try:
            async with AsyncSessionLocal() as db:
                await dispatch(db, row_id)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("rejection_email dispatch failed for id=%s", row_id)
        # Small stagger: Graph is cheap but we're friendly.
        await asyncio.sleep(0.5)
