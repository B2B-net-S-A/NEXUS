"""Pętla maili do kandydatów: podziękowanie i prośba o warunki (17.11.2026).

Co 5 minut, 8:00–20:00 Warszawa, z dziennym limitem. Logika w
``services/candidate_terms_queue.py``; tu tylko rytm, heartbeat i wyłącznik
``CANDIDATE_TERMS_ENABLED``. Mail wychodzi dopiero, gdy admin włączy rodzaj
„Podziękowanie i prośba o warunki” w Ustawieniach → Powiadomienia.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.candidate_terms_queue import process_queue

logger = logging.getLogger(__name__)

LOOP_SLEEP_SECONDS = 300


async def run_once() -> dict:
    async with AsyncSessionLocal() as db:
        stats = await process_queue(db)
    if any(stats.values()):
        logger.info("candidate_terms_sender %s", stats)
    return stats


async def candidate_terms_sender_loop() -> None:
    if not settings.CANDIDATE_TERMS_ENABLED:
        logger.info("candidate_terms_sender disabled")
        return
    beat = loop_heartbeat.register(
        "candidate_terms_sender", max_silence_seconds=LOOP_SLEEP_SECONDS + 900
    )
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("candidate_terms_sender iteration failed")
        await asyncio.sleep(LOOP_SLEEP_SECONDS)
