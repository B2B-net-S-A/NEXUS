"""Automatyczne zamykanie par bez odpowiedzi klienta — co godzinę, dzień roboczy 8–17.

Reguła i wyłącznik: ``services/client_wait.py``. Domyślnie nic nie robi.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.services import client_wait, loop_heartbeat

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600


async def client_wait_loop() -> None:
    beat = loop_heartbeat.register(
        "client_wait", max_silence_seconds=3 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        moment = local_now()
        if moment.weekday() < 5 and 8 <= moment.hour < 17:
            try:
                async with AsyncSessionLocal() as db:
                    result = await client_wait.run_auto_close(db)
                if result["closed"] or result["skipped"]:
                    logger.info("client_wait: %s", result)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("client_wait_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
