"""
Phase 13 — orkiestrator 5 triggerów powiadomień.

Jedna długo-żyjąca pętla asyncio wywołana z `app/main.py` lifespan. Co
`TRIGGERS_LOOP_INTERVAL_SECONDS` (default 5 min) odpala wszystkie 5 triggerów
w jednej transakcji. Triggery wrażliwe na czas (KPI 11:45, Client feedback
16:30) bramkują się same przez `is_within_window()`.

Weekendy są pomijane w całości — pipeline procesowy i tak chodzi Pn–Pt.

NIE rusza istniejącej `slack_sla_alerts_loop` — te dwa mechanizmy współistnieją.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import is_business_day, local_now
from app.services.notification_triggers import run_all_triggers

logger = logging.getLogger(__name__)


async def notification_triggers_loop() -> None:
    """Długo-żyjący task: co N sekund przegląda kandydatów, calle, eventy."""
    interval = max(60, settings.TRIGGERS_LOOP_INTERVAL_SECONDS)
    logger.info(
        "notification_triggers_loop started: interval=%ds tz=%s",
        interval,
        settings.BUSINESS_TZ,
    )
    # Grace period przy starcie aplikacji (reszta bootstrapu ma chwilę na odpalenie).
    await asyncio.sleep(30)

    while True:
        try:
            now = local_now(settings.BUSINESS_TZ)
            if is_business_day(now, settings.BUSINESS_TZ):
                async with AsyncSessionLocal() as db:
                    results = await run_all_triggers(db, now)
                    await db.commit()
                total = sum(results.values())
                if total:
                    logger.info(
                        "notification_triggers_loop: emitted %d — %s",
                        total,
                        results,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("notification_triggers_loop iteration failed")
        await asyncio.sleep(interval)
