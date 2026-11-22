"""Pętla bota Cpro (kontener worker), co 5 minut.

* wygasza biegi bez raportu (ostrzeżenie w logu),
* gdy żaden bieg nie trwa, daje botowi karty z kolejki Cpro bez braków
  (``flow.start_due``), najwyżej ``MAX_ITEMS_PER_RUN`` naraz.

Wyłącznik ``CPRO_BOT_ENABLED`` sprawdzany przed pętlą. Na stagingu pętla stoi
(``STAGING_BLOCKED_TASKS``): webhook do bota w USA i wysyłka do klienta.
Logi: same liczby.
→ docs/claude/integracje/cpro-bot-grok.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date
from app.services import loop_heartbeat
from app.services.cpro_bot import flow, runs

logger = logging.getLogger(__name__)

TICK_SECONDS = 5 * 60


async def cpro_bot_loop() -> None:
    if not runs.enabled():
        logger.info("cpro_bot_loop disabled")
        return
    if not runs.configured():
        logger.warning("cpro_bot_loop enabled without webhook configuration")
    beat = loop_heartbeat.register("cpro_bot", max_silence_seconds=3 * TICK_SECONDS)
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                now = datetime.now(timezone.utc)
                expired = await runs.expire_runs(db, now=now)
                run = await flow.start_due(db, now=now, today=business_date(now))
            if expired or run is not None:
                logger.info(
                    "cpro_bot tick expired=%d started=%d items=%d",
                    expired,
                    int(run is not None),
                    len(run.stage_ids or []) if run is not None else 0,
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("cpro_bot_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
