"""Pętla ekranu Ustawienia → Bezpieczeństwo (0800) — reguły w ``services``.

Co 30 min (``SECURITY_SYNC_INTERVAL_SECONDS``): biegi ``security-weekly.yml``
z GitHub API, znaleziska z DefectDojo (gdy skonfigurowane), wyjątki po
terminie z powrotem na listę i dzwonek do adminów o rutynach po terminie
(dedup dzienny w ``emit``). Każdy krok osobno — błąd jednego nie zatrzymuje
reszty.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services import loop_heartbeat
from app.services.security_screen import expire_exceptions, notify_overdue_routines
from app.services.security_sync import sync_all

logger = logging.getLogger(__name__)


async def run_once() -> None:
    today = business_today()
    try:
        async with AsyncSessionLocal() as db:
            await sync_all(db)
    except Exception:
        logger.exception("security_sync: source sync failed; next run retries")
    try:
        async with AsyncSessionLocal() as db:
            expired = await expire_exceptions(db, today)
            sent = await notify_overdue_routines(db, today)
            await db.commit()
        if expired or sent:
            logger.info("security_sync: expired=%s bells=%s", expired, sent)
    except Exception:
        logger.exception("security_sync: exceptions/routines failed; next run retries")


async def security_sync_loop() -> None:
    if not settings.SECURITY_SYNC_ENABLED:
        logger.info("security_sync: disabled (SECURITY_SYNC_ENABLED=false)")
        return
    interval = max(300, settings.SECURITY_SYNC_INTERVAL_SECONDS)
    beat = loop_heartbeat.register(
        "security_sync", max_silence_seconds=interval * 3 + 600
    )
    await asyncio.sleep(240)
    while True:
        beat.tick()
        await run_once()
        await asyncio.sleep(interval)
