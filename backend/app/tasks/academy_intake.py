"""Akademia — pętla tła: nabór z ogłoszeń i sortowanie Luną co 10 minut.

Bez programów nic się nie dzieje (brak zapytań do modelu). Wyłącznik
``ACADEMY_INTAKE_ENABLED`` kończy pętlę przed ``while True`` — przycisk
„Pobierz zgłoszenia” na ekranie działa niezależnie od niego.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services.academy import sync_all_active

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 180
_INTERVAL_SECONDS = 600


async def academy_intake_loop() -> None:
    """Rejestrowana w lifespanie ``main.py``."""
    if not settings.ACADEMY_INTAKE_ENABLED:
        logger.info("academy_intake: wyłączone (ACADEMY_INTAKE_ENABLED=false)")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        try:
            results = await sync_all_active()
            busy = {pid: stats for pid, stats in results.items() if any(stats.values())}
            if busy:
                logger.info("academy_intake: %s", busy)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("academy_intake: cykl padł")
        await asyncio.sleep(_INTERVAL_SECONDS)
