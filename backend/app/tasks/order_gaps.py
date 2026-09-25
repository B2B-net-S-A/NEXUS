"""Dzienna pętla Braków (Finanse → Zmiany w zamówieniach).

Brak ma „pojawić się następnego dnia po zakończeniu zamówienia", więc pętla
biegnie tuż po północy w Warszawie — i raz przy starcie, bo Coolify restartuje
kontener przy każdym pushu na main, a przebieg o 00:30 łatwo przespać.
Przebieg jest idempotentny (UNIQUE na zamówieniu), więc dodatkowe biegi nic
nie psują.

Uzupełnienie braku NIE czeka na tę pętlę: robi to ``commit_order_write`` przy
zapisie zamówienia, a odczyt zakładki w Finansach dosypuje świeże wykrycia.

Ten sam bieg dosypuje formułę faktury Nordei zamówieniom z PDF-em, które jej
nie mają (``nordea_invoice_lines.fill_missing``) — przy starcie obejmuje to
zamówienia sprzed wdrożenia.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import seconds_until_local_time
from app.services.order_gaps import GapRunResult, run_order_gaps
from app.services import loop_heartbeat, nordea_invoice_lines

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
    await _fill_nordea_invoice_lines()
    return result


async def _fill_nordea_invoice_lines() -> None:
    """Formuła faktury Nordei dla zamówień, którym jej brakuje (ticket 8).

    Osobna sesja i osobny błąd: odczyt PDF-ów nie może wstrzymać Braków.
    """
    async with AsyncSessionLocal() as db:
        try:
            filled = await nordea_invoice_lines.fill_missing(db)
            await db.commit()
        except Exception:  # noqa: BLE001
            await db.rollback()
            logger.exception("Nordea invoice lines backfill failed")
            return
    if filled:
        logger.info("Nordea invoice lines filled: %d", filled)


async def order_gaps_loop() -> None:
    if not settings.ORDER_GAPS_ENABLED:
        logger.info("order_gaps_loop disabled (ORDER_GAPS_ENABLED=false)")
        return
    # MON-04: tick na początku iteracji; cisza dłuższa niż próg = „stalled”.
    beat = loop_heartbeat.register("order_gaps", max_silence_seconds=27 * 3600)
    while True:
        beat.tick()
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
