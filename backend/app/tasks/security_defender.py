"""Pętla źródła „Microsoft Defender” ekranu Bezpieczeństwo — reguły w
``services/security_defender.py``.

Co 15 min (``DEFENDER_SYNC_INTERVAL_SECONDS``, najmniej 5 min) incydenty
i Secure Score z Microsoft Graph. Bez poświadczeń rejestracji aplikacji
(``DEFENDER_CLIENT_ID``/``DEFENDER_CLIENT_SECRET``) bieg nic nie robi, a ekran
pokazuje źródło jako „nieskonfigurowane”. Na stagingu zatrzymana
(``app/core/staging.py``): kopia produkcji nie może dzwonić adminom
incydentami z prawdziwego tenanta; bieg ręczny: ``run_once``.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.security_defender import DefenderSyncResult, sync_once

logger = logging.getLogger(__name__)


async def run_once() -> DefenderSyncResult | None:
    try:
        async with AsyncSessionLocal() as db:
            return await sync_once(db)
    except Exception:
        logger.exception("security_defender: sync failed; next run retries")
        return None


async def security_defender_loop() -> None:
    if not settings.DEFENDER_SYNC_ENABLED:
        logger.info("security_defender: disabled (DEFENDER_SYNC_ENABLED=false)")
        return
    interval = max(300, settings.DEFENDER_SYNC_INTERVAL_SECONDS)
    beat = loop_heartbeat.register(
        "security_defender", max_silence_seconds=interval * 3 + 600
    )
    await asyncio.sleep(300)
    while True:
        beat.tick()
        await run_once()
        await asyncio.sleep(interval)
