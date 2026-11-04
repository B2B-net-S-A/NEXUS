"""Godzinna synchronizacja uczestników rekrutacji z kategoriami kompetencji.

Zmiana kategorii rekrutacji i zmiana składu kategorii wyrównują uczestników
od razu, w swojej transakcji. Ta pętla łapie resztę: zmianę roli, wyłączone
konto, import z Traffita, rekrutację otwartą ponownie — żadna z tych ścieżek
nie wie o uczestnikach.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.auto_cc_collaborators import sync_cc_participants

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600
_INITIAL_DELAY_SECONDS = 90


async def run_once() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        try:
            result = await sync_cc_participants(db)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            raise
    return result


async def cc_participants_sync_loop() -> None:
    # MON-04: tick na początku iteracji; cisza dłuższa niż próg = „stalled”.
    beat = loop_heartbeat.register(
        "cc_participants_sync", max_silence_seconds=_INTERVAL_SECONDS + 1800
    )
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            result = await run_once()
            if result["added"] or result["removed"]:
                logger.info("cc_participants_sync: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("cc_participants_sync_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
