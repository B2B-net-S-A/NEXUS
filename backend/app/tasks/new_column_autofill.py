"""Pętla silnika „System trzyma Nowych na 20” (23.10.2026).

Cała logika jest w `services/new_column_autofill.py`; tu tylko rytm. Pętla
budzi się co `NEW_COLUMN_AUTOFILL_INTERVAL_SECONDS`; poza dniami roboczymi
7–19 nic nie robi.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 120


async def new_column_autofill_loop() -> None:
    from app.services import new_column_autofill

    if not new_column_autofill.enabled():
        logger.info(
            "[new_column_autofill] disabled (NEW_COLUMN_AUTOFILL_ENABLED=false)"
        )
        return
    interval = max(30, int(settings.NEW_COLUMN_AUTOFILL_INTERVAL_SECONDS))
    beat = loop_heartbeat.register(
        "new_column_autofill", max_silence_seconds=interval + 1800
    )
    logger.info("[new_column_autofill] loop started (interval=%ss)", interval)
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            outcome = await new_column_autofill.tick()
            if outcome.get("filled"):
                logger.info("[new_column_autofill] %s", outcome)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla nie może umrzeć
            logger.warning("[new_column_autofill] tick failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)
