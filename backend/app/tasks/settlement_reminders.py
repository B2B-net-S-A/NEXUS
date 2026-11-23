"""Przypomnienia o brakującym raporcie godzin (co godzinę, od 9:00 w dni robocze).

Krok dnia liczy ``services/client_settlements/reminders.step_for``: 3. dzień
roboczy miesiąca po rozliczanym — mail do konsultanta (gdy panel na to
pozwala), 5. — mail z opiekunem w kopii, 7. — dzwonek opiekuna. Inne dni
pętla nic nie robi. Domyślnie wyłączona przełącznikiem w karcie „Start
rozliczeń”; na stagingu zatrzymana (``app/core/staging.py``), bo to wysyłka
do ludzi spoza firmy.

Powtórki tego samego dnia zatrzymuje unikat dziennika
``client_settlement_reminders`` (rezerwacja przed wysyłką), więc budzenie co
godzinę i restart przy wdrożeniu niczego nie dublują.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, is_business_day, local_now
from app.services import loop_heartbeat
from app.services.client_settlements import reminders

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_HOUR = 9


async def run_once(now: datetime | None = None) -> dict[str, Any] | None:
    moment = now or local_now()
    if moment.hour < FIRST_HOUR or not is_business_day(moment):
        return None
    async with AsyncSessionLocal() as db:
        try:
            result = await reminders.run_step(db, business_date(moment))
        except Exception:
            await db.rollback()
            raise
    return result if result.get("status") == "done" else None


async def settlement_reminders_loop() -> None:
    beat = loop_heartbeat.register(
        "settlement_reminders", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            result = await run_once()
            if result:
                logger.info("settlement_reminders: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("settlement_reminders_loop iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
