"""Pętla maili CPro — co 3 minuty, także poza godzinami pracy.

Przebieg i reguły: ``services/cpro_mail.py``. Mail jest w NEXUSIE zwykle po
ok. 3 minutach od odebrania, więc rekruter dowiaduje się w ciągu kilku minut.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import loop_heartbeat
from app.services.cpro_mail import run_once_safely

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 180


async def cpro_mail_loop() -> None:
    # Dziesięć przebiegów ciszy = pętla stoi.
    beat = loop_heartbeat.register(
        "cpro_mail", max_silence_seconds=10 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        if settings.CPRO_MAIL_ENABLED:
            try:
                await run_once_safely()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("cpro_mail_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
