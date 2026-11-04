"""„Jakość QC” raz na dobę — trafność sprawdzeń i ich stan (D6, 13.10.2026).

Uwaga QC z trafnością poniżej 70% przy co najmniej 30 pokazanych pozycjach
sama staje się informacją; blokada poniżej 90% daje jedno powiadomienie do
adminów na serię (`services/qc_quality.py`). Stan leży pod blokadą wiersza
`app_settings`, więc kilka procesów naraz nie zdubluje powiadomień.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import qc_quality

logger = logging.getLogger(__name__)

# Start aplikacji ma pierwszeństwo; potem raz na dobę.
_START_DELAY_SECONDS = 600
_INTERVAL_SECONDS = 24 * 3600


async def qc_quality_daily_loop() -> None:
    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        try:
            async with AsyncSessionLocal() as db:
                await qc_quality.refresh_states(db)
                await db.commit()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — zadanie tła nie może paść
            logger.warning("qc quality: refresh failed (%s)", type(exc).__name__)
        await asyncio.sleep(_INTERVAL_SECONDS)
