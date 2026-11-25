"""Pętla historii stawek z faktur KSeF (0782, worker).

Co ``_TICK_SECONDS``: reguła ``contract_rate_history.infer`` dla wszystkich
kontraktów z fakturami (sprzedaż i faktury konsultantów z KSeF), podpowiedzi
na kartę kontraktu, a przy ``CONTRACT_RATE_HISTORY_AUTO_APPLY`` wpis
podpowiedzi jednoznacznych, które nie zmieniają dzisiejszej stawki (decyzja
Artura 25.11.2026). Faktury przychodzą raz dziennie, więc przebieg co 6 h
wystarcza. ``CONTRACT_RATE_HISTORY_ENABLED=false`` wyłącza pętlę.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today
from app.services import loop_heartbeat
from app.services.contract_rate_history import service

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 420
_TICK_SECONDS = 6 * 3600


async def run_cycle() -> dict[str, int]:
    async with AsyncSessionLocal() as db:
        return await service.run(
            db,
            business_today(),
            auto_apply=settings.CONTRACT_RATE_HISTORY_AUTO_APPLY,
        )


async def contract_rate_history_loop() -> None:
    if not settings.CONTRACT_RATE_HISTORY_ENABLED:
        logger.info("contract_rate_history_loop disabled")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "contract_rate_history", max_silence_seconds=_TICK_SECONDS + 3 * 3600
    )
    while True:
        beat.tick()
        try:
            stats = await run_cycle()
            logger.info("contract_rate_history: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("contract_rate_history: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
