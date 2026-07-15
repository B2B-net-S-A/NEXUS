"""Background drain for the indexing outbox (plan PR5).

Flag-gated: exits immediately unless ``AI_INDEX_WORKER_ENABLED`` is set. Polls
every ``AI_INDEX_WORKER_INTERVAL_SECONDS`` (clamped ≥5s) and drains one batch
per tick via ``index_outbox_service.drain_once`` (claim → build doc+hash →
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
    batch = int(getattr(settings, "AI_INDEX_WORKER_BATCH", 50))
    logger.info(
        "[index-outbox] worker started (interval=%ss, batch=%s)", interval, batch
    )

    while True:
        try:
            async with AsyncSessionLocal() as db:
                counts = await outbox.drain_once(db, batch=batch)
            if counts:
                logger.info("[index-outbox] drained batch: %s", counts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — a worker tick must never die
            logger.warning("[index-outbox] tick failed: %s", exc)
        await asyncio.sleep(interval)
