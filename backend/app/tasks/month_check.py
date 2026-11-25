"""Pętla kontroli miesiąca (0784): rozbieżności faktur klient ↔ konsultant.

Co godzinę: raz na dzień po ``RUN_HOUR`` (Warszawa) przebieg
``month_check.service.run`` dla trzech zamkniętych miesięcy (faktury z KSeF
przychodzą w ciągu dnia, więc noc wystarcza), a potem maile do Finansów
(poniedziałek — nowe sprawy z tygodnia, 12. dzień — podsumowanie miesiąca).
Dzień ostatniego przebiegu leży w ``app_settings['month_check_last_run']``,
więc restart nie liczy drugi raz. ``MONTH_CHECK_ENABLED=false`` wyłącza pętlę.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.services import loop_heartbeat
from app.services.month_check import mail, service

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 540
_TICK_SECONDS = 3600
RUN_HOUR = 3


def due(last_run_iso: str | None, now_local: datetime) -> bool:
    """Przebieg należny: po ``RUN_HOUR`` i nie dziś."""

    if now_local.hour < RUN_HOUR:
        return False
    if not last_run_iso:
        return True
    try:
        last = datetime.fromisoformat(last_run_iso).astimezone(now_local.tzinfo)
    except ValueError:
        return True
    return last.date() < now_local.date()


async def run_cycle(now_local: datetime) -> dict[str, object]:
    out: dict[str, object] = {}
    async with AsyncSessionLocal() as db:
        info = await service.last_run(db)
        if due(info.get("executed_at"), now_local):
            out["run"] = await service.run(db, now_local.date())
        out["mail"] = await mail.tick(db, now_local)
    return out


async def month_check_loop() -> None:
    if not settings.MONTH_CHECK_ENABLED:
        logger.info("month_check_loop disabled")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "month_check", max_silence_seconds=_TICK_SECONDS + 3 * 3600
    )
    while True:
        beat.tick()
        try:
            stats = await run_cycle(local_now())
            if stats.get("run") or any((stats.get("mail") or {}).values()):
                logger.info("month_check: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("month_check: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
