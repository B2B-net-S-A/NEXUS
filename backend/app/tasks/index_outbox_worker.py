"""Background drain for the indexing outbox (plan PR5).

Flag-gated: exits immediately unless ``AI_INDEX_WORKER_ENABLED`` is set. Polls
every ``AI_INDEX_WORKER_INTERVAL_SECONDS`` (clamped ≥5s) when idle or after an
error. Full successful batches use a shorter configurable pause (clamped ≥1s).
Drains one batch per tick via ``index_outbox_service.drain_once`` (claim → build doc+hash →
upsert/delete → done/failed/dead). Restart-safe: state lives in the DB, so a
Coolify rebuild never re-triggers a mass re-embed.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import index_outbox_service as outbox

logger = logging.getLogger(__name__)


async def index_outbox_loop() -> None:
    if not outbox.worker_enabled():
        logger.info("[index-outbox] worker disabled (AI_INDEX_WORKER_ENABLED=false)")
        return

    interval = max(5, int(getattr(settings, "AI_INDEX_WORKER_INTERVAL_SECONDS", 30)))
    busy_interval = max(
        1, int(getattr(settings, "AI_INDEX_WORKER_BUSY_INTERVAL_SECONDS", 1))
    )
    batch = int(getattr(settings, "AI_INDEX_WORKER_BATCH", 50))
    logger.info(
        "[index-outbox] worker started (interval=%ss, batch=%s)", interval, batch
    )

    while True:
        delay = interval
        try:
            async with AsyncSessionLocal() as db:
                counts = await outbox.drain_once(db, batch=batch)
            if counts:
                logger.info("[index-outbox] drained batch: %s", counts)
            # drain_once commits before returning. Only accelerate when every
            # claimed event succeeded and the batch was full. Partial failures,
            # exhausted provider retries, DB errors and idle polls keep the normal pause.
            if batch > 0 and counts == {"done": batch}:
                delay = busy_interval
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a worker tick must never die
            logger.warning("[index-outbox] tick failed: %s", exc)
        await asyncio.sleep(delay)
