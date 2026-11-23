"""Rozliczenia klientów: poranne przyjęcie RCP „Bez uwag” (reguła
``order.auto_accept_clean``, decyzja Artura 23.11.2026).

Pętla budzi się co godzinę, a przyjmuje raz dziennie: w dzień roboczy między
7:00 a 12:00, przy pierwszym ticku w tym oknie. Restart w ciągu dnia powtarza
bieg, co niczego nie dubluje, bo przyjęte rozliczenie nie ma już stanu ``ok``.
Logika i odmowy: ``services/client_settlements/auto_accept.py``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, local_now
from app.services import loop_heartbeat
from app.services.client_settlements import auto_accept

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600


async def run_once(now: datetime | None = None) -> int:
    moment = now or local_now()
    async with AsyncSessionLocal() as db:
        try:
            accepted = await auto_accept.run(db, now=moment)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    return accepted


async def client_settlements_auto_accept_loop() -> None:
    beat = loop_heartbeat.register(
        "client_settlements_auto_accept", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    last_day: date | None = None
    while True:
        beat.tick()
        try:
            now = local_now()
            if auto_accept.morning(now) and business_date(now) != last_day:
                accepted = await run_once(now)
                last_day = business_date(now)
                if accepted:
                    logger.info("client_settlements_auto_accept: %s RCP", accepted)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("client_settlements_auto_accept_loop iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
