"""Rekrutacja własna: co 5 minut import, licznik odpowiedzi, ponowienia, przypomnienia."""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.own_hiring import sweep

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 300


async def own_hiring_loop() -> None:
    beat = loop_heartbeat.register(
        "own_hiring", max_silence_seconds=4 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                result = await sweep.run_once(db)
            if any(result.values()):
                logger.info("own_hiring: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("own_hiring_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
