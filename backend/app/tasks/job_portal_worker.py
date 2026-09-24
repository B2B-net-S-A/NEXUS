"""Worker kolejki publikacji na portalach (0360).

Kończy się PRZED pętlą, gdy żaden portal nie jest włączony
(``PORTAL_PRACUJ_ENABLED``, ``PORTAL_JJIT_ENABLED``) — wtedy się nie
rejestruje w ``loop_heartbeat`` i nie może być „stalled”. Włączony: tick na
początku każdej iteracji, jedna transakcja na paczkę, błąd paczki
logowany i ponawiany w następnym biegu.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import job_portals, loop_heartbeat

logger = logging.getLogger(__name__)

_MIN_INTERVAL_SECONDS = 15


async def job_portal_worker_loop() -> None:
    if not job_portals.any_enabled():
        logger.info("job_portal_worker disabled — żaden portal nie jest włączony")
        return

    from app.services.job_portals.service import process_batch

    interval = max(
        _MIN_INTERVAL_SECONDS, int(settings.JOB_PORTAL_WORKER_INTERVAL_SECONDS)
    )
    beat = loop_heartbeat.register(
        "job_portal_worker", max_silence_seconds=interval + 900
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                processed = await process_batch(db)
                await db.commit()
            if processed:
                logger.info("job_portal_worker processed=%s", processed)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — kolejka ponowi w następnym biegu
            logger.error("job_portal_worker batch failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)
