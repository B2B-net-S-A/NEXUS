"""Pętla alarmu o masowym przeglądaniu CV (0505) — reguły w ``services``."""

from __future__ import annotations

import asyncio
import logging
import os

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.candidate_data_access_alerts import scan_once

logger = logging.getLogger(__name__)

CHECK_INTERVAL_SECONDS = max(
    60, int(os.environ.get("DATA_ACCESS_ALERT_INTERVAL_SECONDS", "300"))
)


def enabled() -> bool:
    return (
        os.environ.get("DATA_ACCESS_ALERTS_ENABLED", "true").strip().lower() != "false"
    )


async def candidate_data_access_alerts_loop() -> None:
    if not enabled():
        logger.info("data_access_alerts: disabled (DATA_ACCESS_ALERTS_ENABLED=false)")
        return
    # Pętla bezpieczeństwa: zawieszona = brak alarmów, więc ma heartbeat.
    beat = loop_heartbeat.register(
        "candidate_data_access_alerts",
        max_silence_seconds=CHECK_INTERVAL_SECONDS * 3 + 300,
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                sent = await scan_once(db)
            if sent:
                logger.info("data_access_alerts: %s notifications", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("data_access_alerts: scan failed; next run retries")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
