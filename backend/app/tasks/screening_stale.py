"""Pętla kart bez śladu — co 15 minut, tylko w dzień roboczy.

Reguła i przebieg: ``services/screening_stale.py``. Karta wraca w dniu
powrotu przy pierwszym przebiegu po północy (przed blokadą porcji o 7:00),
a dedup dobowy dzwonka sprawia, że restart przy deployu nie dzwoni drugi raz.
Na stagingu zatrzymana (kopia produkcji, wspólna baza sesji): ręcznie
``python -m scripts.screening_stale_return``.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import loop_heartbeat
from app.services.screening_stale import run_once_safely

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 15 * 60


async def screening_stale_loop() -> None:
    # Weekend i święta przebieg kończy od razu, więc heartbeat bije i wtedy.
    beat = loop_heartbeat.register(
        "screening_stale", max_silence_seconds=4 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        if settings.SCREENING_STALE_RETURN_ENABLED:
            try:
                await run_once_safely()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("screening_stale_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
