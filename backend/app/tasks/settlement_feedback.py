"""Informacja zwrotna o wadach rozliczenia (co godzinę, od 9:00 w dni robocze).

``services/client_settlements/feedback.run`` zapisuje wady miesięcy
(poprzedni i jeszcze jeden), zamyka poprawione i wysyła komunikaty, którym
przyszedł termin: pierwszy od razu, potem co ``every_days`` dni roboczych.
Domyślnie wyłączona (``app_settings['client_settlement_feedback']``); na
stagingu zatrzymana (``app/core/staging.py``), bo to wysyłka do ludzi.

Powtórki tego samego dnia zatrzymuje rezerwacja ``last_sent_on`` przed
wysyłką, więc budzenie co godzinę i restart przy wdrożeniu niczego nie dublują.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_date, is_business_day, local_now
from app.services import loop_heartbeat
from app.services.client_settlements import feedback

logger = logging.getLogger(__name__)

INTERVAL_SECONDS = 3600
FIRST_HOUR = 9


async def run_once(now: datetime | None = None) -> dict[str, Any] | None:
    moment = now or local_now()
    if moment.hour < FIRST_HOUR or not is_business_day(moment):
        return None
    async with AsyncSessionLocal() as db:
        try:
            result = await feedback.run(db, business_date(moment))
        except Exception:
            await db.rollback()
            raise
    return result if result.get("status") == "done" else None


async def settlement_feedback_loop() -> None:
    beat = loop_heartbeat.register(
        "settlement_feedback", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            result = await run_once()
            if result:
                # Same liczby: bez adresów, nazwisk i treści.
                logger.info("settlement_feedback: %s", result)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("settlement_feedback_loop iteration failed")
        await asyncio.sleep(INTERVAL_SECONDS)
