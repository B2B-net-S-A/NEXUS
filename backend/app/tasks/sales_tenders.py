"""Pętla przetargów (kontener worker): w dni robocze od 5:30 jeden bieg dziennie.

Bieg (``services/sales/tenders/flow.py``) pobiera ogłoszenia z BZP i TED, zakłada
szanse z tych, które przeszły bramkę, i zamyka szanse od bramki, którym minął
termin składania ofert (decyzja Artura 24.11.2026, wariant B). Nieudany bieg
ponawia się po godzinie, najwyżej trzy próby dziennie. Wyłącznik
``SALES_TENDERS_ENABLED`` sprawdzany przed pętlą; na stagingu pętla stoi
(``STAGING_BLOCKED_TASKS``). Logi: same liczby.
→ docs/claude/sprzedaz/przetargi-z-rejestrow.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, time, timedelta
from typing import Any

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, is_business_day, local_now
from app.services import loop_heartbeat
from app.services.sales.tenders import flow, sources

logger = logging.getLogger(__name__)

TICK_SECONDS = 15 * 60
RUN_AT = time(5, 30)
RETRY_AFTER = timedelta(hours=1)
MAX_ATTEMPTS_PER_DAY = 3


def should_run(state: dict[str, Any], *, local: datetime, attempts: int) -> bool:
    """Czy pętla ma teraz zacząć bieg (dzień roboczy, po 5:30, bez udanego dziś)."""

    if attempts >= MAX_ATTEMPTS_PER_DAY or not is_business_day(local):
        return False
    if local.time() < RUN_AT:
        return False
    run = flow.last_run_view(state, now=local) or {}
    if run.get("status") == "running":
        return False
    started = sources.parse_instant(run.get("started_at"))
    if started is None or business_date(started) != local.date():
        return True
    if run.get("status") == "ok":
        return False
    return local - started >= RETRY_AFTER


async def sales_tenders_loop() -> None:
    if not settings.SALES_TENDERS_ENABLED:
        logger.info("sales_tenders_loop disabled")
        return
    beat = loop_heartbeat.register(
        "sales_tenders", max_silence_seconds=TICK_SECONDS + 3600
    )
    attempts: dict[date, int] = {}
    while True:
        beat.tick()
        try:
            local = local_now()
            async with AsyncSessionLocal() as db:
                state = await flow.load_state(db)
            today = local.date()
            if should_run(state, local=local, attempts=attempts.get(today, 0)):
                attempts = {today: attempts.get(today, 0) + 1}
                await flow.run(trigger="schedule")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("sales_tenders_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
