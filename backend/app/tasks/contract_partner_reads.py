"""Pętla danych firm z umów (E5a, 0755, worker).

Co ``_TICK_SECONDS``: odczyt paczki głównych plików umów aktywnych kontraktów
B2B, które nie mają danych firmy Partnera w Generatorze (pierwszy bieg
nadrabia ok. 370 kontraktów z kopii produkcji z 19.11.2026). Każdy plik we
własnej transakcji — jeden zły plik nie zatrzymuje reszty. Rejestrów firm
pętla nie woła (limity); sprawdza je człowiek przyciskiem.
``CONTRACT_PARTNER_READ_ENABLED=false`` (domyślnie) wyłącza pętlę.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.contract_partner_reads import service

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 240
_TICK_SECONDS = 600
_BATCH = 25


async def run_cycle() -> dict[str, int]:
    stats = {"read": 0, "failed": 0}
    async with AsyncSessionLocal() as db:
        pending = (await service.scan(db)).pending[:_BATCH]
    for doc in pending:
        async with AsyncSessionLocal() as db:
            try:
                row = await service.read_document_row(db, doc)
                await db.commit()
                stats["read" if row.status == "read" else "failed"] += 1
            except Exception:  # noqa: BLE001 — jeden plik nie zatrzymuje paczki
                await db.rollback()
                stats["failed"] += 1
                logger.exception("contract_partner_reads: plik %s", doc.id)
    return stats


async def contract_partner_reads_loop() -> None:
    if not settings.CONTRACT_PARTNER_READ_ENABLED:
        logger.info("contract_partner_reads_loop disabled")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "contract_partner_reads", max_silence_seconds=_TICK_SECONDS + 3 * 3600
    )
    while True:
        beat.tick()
        try:
            stats = await run_cycle()
            if any(stats.values()):
                logger.info("contract_partner_reads: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("contract_partner_reads: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
