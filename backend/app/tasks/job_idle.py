"""Pętla rekrutacji bez ruchu — co godzinę, działa w dzień roboczy 8–17.

Przebieg i reguła: ``services/job_idle.py``. Znaczniki etapów i dedup dobowy
dzwonka sprawiają, że kolejne przebiegi tego samego dnia nic nie powtarzają,
a restart przy deployu niczego nie wysyła drugi raz.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import loop_heartbeat
from app.services.job_idle import run_once_safely

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 3600


async def job_idle_loop() -> None:
    # Przebieg co godzinę; trzy godziny ciszy = pętla stoi.
    beat = loop_heartbeat.register(
        "job_idle", max_silence_seconds=3 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        if settings.JOB_IDLE_ENABLED:
            try:
                await run_once_safely()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("job_idle_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
