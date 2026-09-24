"""Pętla list telefonów praktykantów (0372).

Rano w dni robocze (okno ``TRAINEE_CALL_LISTS_HOUR``–+1 h, ``BUSINESS_TZ``)
składa listy wszystkim aktywnym programom i zapisuje statystyki puli; raz na
dzień sprawdza, czy komuś kończy się program (powiadomienie o decyzji).
Brak listy rano nie jest awarią — pierwsze ``GET /api/trainee/today`` ją
złoży. Wyłącznik ``TRAINEE_CALL_LISTS_ENABLED``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date
from typing import Optional

from app.core.config import settings
from app.core.scheduling import business_today, local_now
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 600
_INITIAL_DELAY_SECONDS = 120


async def _run_day(today: date) -> dict:
    from app.core.database import AsyncSessionLocal
    from app.services import trainee_call_list as lists
    from app.services import trainee_program as program_service
    from app.services import trainee_rules as rules_mod

    async with AsyncSessionLocal() as db:
        notified = await program_service.notify_due_decisions(db, today=today)
        await db.commit()
    if not rules_mod.is_workday(today):
        return {"notified": notified, "lists": {}}
    async with AsyncSessionLocal() as db:
        programs = await lists.active_programs(db, today=today)
        created: dict[int, int] = {}
        if programs:
            rules = await lists.load_rules(db)
            ranked = await lists.cached_ranking(db, rules, today=today)
            created = await lists.generate_lists(
                db, programs, today=today, ranked=ranked
            )
            await db.commit()
            stats = await lists.pool_stats(db, rules, today=today)
            await lists.store_pool_stats(db, stats)
            await db.commit()
    return {"notified": notified, "lists": created}


async def trainee_call_lists_loop() -> None:
    if not settings.TRAINEE_CALL_LISTS_ENABLED:
        logger.info("[trainee_call_lists] disabled (TRAINEE_CALL_LISTS_ENABLED=false)")
        return
    beat = loop_heartbeat.register(
        "trainee_call_lists", max_silence_seconds=_INTERVAL_SECONDS + 1800
    )
    hour = int(settings.TRAINEE_CALL_LISTS_HOUR)
    last_day: Optional[date] = None
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            now = local_now(settings.BUSINESS_TZ)
            today = business_today(settings.BUSINESS_TZ)
            if last_day != today and now.hour >= hour:
                outcome = await _run_day(today)
                last_day = today
                logger.info("[trainee_call_lists] %s %s", today.isoformat(), outcome)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla nie może umrzeć
            logger.warning("[trainee_call_lists] tick failed: %s", type(exc).__name__)
        await asyncio.sleep(_INTERVAL_SECONDS)
