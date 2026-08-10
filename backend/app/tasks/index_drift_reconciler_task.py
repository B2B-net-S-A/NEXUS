"""Periodic sweep that keeps the vector index honest without asking writers.

Flag-gated and OFF by default. It walks candidates and jobs in batches, one
batch per tick, carrying a cursor across ticks — so a full pass is spread over
hours instead of arriving as one spike, and a restart resumes from the start of
the current pass rather than re-doing everything.

Ordering matters and is not optional: this must not run before the provider
health probes exist. With ``AI_INDEX_MAX_ATTEMPTS=5``, a Voyage outage plus a
reconciler feeding the worker quietly burns the whole backlog into dead rows,
and the healthcheck would have shown green throughout.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import index_drift_reconciler as reconciler
from app.services import index_outbox_service as outbox

logger = logging.getLogger(__name__)


def reconciler_enabled() -> bool:
    return bool(getattr(settings, "AI_INDEX_RECONCILER_ENABLED", False))


async def index_drift_reconciler_loop() -> None:
    if not reconciler_enabled():
        logger.info(
            "[index-drift] reconciler disabled (AI_INDEX_RECONCILER_ENABLED=false)"
        )
        return

    interval = max(
        30, int(getattr(settings, "AI_INDEX_RECONCILER_INTERVAL_SECONDS", 300))
    )
    batch = int(getattr(settings, "AI_INDEX_RECONCILER_BATCH", 500))
    logger.info(
        "[index-drift] reconciler started (interval=%ss, batch=%s)", interval, batch
    )

    # One cursor per entity type; a completed pass resets to 0 and starts over.
    cursors: dict[str, int] = {outbox.CANDIDATE: 0, outbox.JOB: 0}

    while True:
        for entity_type in (outbox.CANDIDATE, outbox.JOB):
            try:
                async with AsyncSessionLocal() as db:
                    result = await reconciler.reconcile_once(
                        db,
                        entity_type=entity_type,
                        batch=batch,
                        cursor=cursors[entity_type],
                    )
                    await db.commit()
                if result.next_cursor is None:
                    logger.info(
                        "[index-drift] %s: pass complete, restarting", entity_type
                    )
                    cursors[entity_type] = 0
                else:
                    cursors[entity_type] = result.next_cursor
                    if result.drifted:
                        logger.info(
                            "[index-drift] %s: %s", entity_type, result.as_log()
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — a tick must never kill the loop
                logger.warning("[index-drift] %s tick failed: %s", entity_type, exc)
        await asyncio.sleep(interval)
