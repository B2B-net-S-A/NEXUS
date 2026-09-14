"""Dzienna pętla Braków (Finanse → Zmiany w zamówieniach).

Brak ma „pojawić się następnego dnia po zakończeniu zamówienia", więc pętla
biegnie tuż po północy w Warszawie — i raz przy starcie, bo Coolify restartuje
kontener przy każdym pushu na main, a przebieg o 00:30 łatwo przespać.
Przebieg jest idempotentny (UNIQUE na zamówieniu), więc dodatkowe biegi nic
nie psują.

Uzupełnienie braku NIE czeka na tę pętlę: robi to ``commit_order_write`` przy
zapisie zamówienia, a odczyt zakładki w Finansach dosypuje świeże wykrycia.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import seconds_until_local_time
from app.services.order_gaps import GapRunResult, run_order_gaps

logger = logging.getLogger(__name__)


async def run_once() -> GapRunResult:
    async with AsyncSessionLocal() as db:
        try:
            result = await run_order_gaps(db)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            raise
    logger.info("Order gaps run: %s", result)
    return result


async def order_gaps_loop() -> None:
    if not settings.ORDER_GAPS_ENABLED:
        logger.info("order_gaps_loop disabled (ORDER_GAPS_ENABLED=false)")
        return
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("order_gaps_loop iteration failed")
        delay = seconds_until_local_time(
            datetime.now(timezone.utc),
            settings.ORDER_GAPS_RUN_HOUR_LOCAL,
            settings.ORDER_GAPS_RUN_MINUTE_LOCAL,
        )
        await asyncio.sleep(max(delay, 60.0))
