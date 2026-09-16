"""Dobowy import JJIT/RocketJobs (etap 2 planu integracji).

Codziennie o ``JJIT_RUN_HOUR_LOCAL:JJIT_RUN_MINUTE_LOCAL`` (Europe/Warsaw)
— ta sama pora, o której chodził scraper na Macu (13:00), żeby w tygodniu
równoległej obserwacji liczby były porównywalne. Kill-switch ``JJIT_ENABLED``
sprawdzany PRZED pętlą (konwencja repo). Sam run żyje w
``services.integrations.jjit.runner`` — pętla tylko wyznacza porę.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.scheduling import seconds_until_local_time
from app.services import loop_heartbeat
from app.services.integrations.jjit.runner import RunInProgress, run_once

logger = logging.getLogger(__name__)


async def jjit_import_loop() -> None:
    if not settings.JJIT_ENABLED:
        logger.info("jjit_import_loop disabled (JJIT_ENABLED=false)")
        return
    beat = loop_heartbeat.register("jjit_import", max_silence_seconds=27 * 3600)
    while True:
        delay = seconds_until_local_time(
            datetime.now(timezone.utc),
            settings.JJIT_RUN_HOUR_LOCAL,
            settings.JJIT_RUN_MINUTE_LOCAL,
        )
        beat.tick()
        await asyncio.sleep(max(delay, 60.0))
        beat.tick()
        try:
            result = await run_once()
            logger.info("jjit import: %s", result)
        except RunInProgress:
            logger.info("jjit import: pominięty — run ręczny w toku")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("jjit_import_loop iteration failed")
