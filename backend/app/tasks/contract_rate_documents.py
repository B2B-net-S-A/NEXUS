"""Pętla stawek z dokumentów kontraktu (0739, worker).

Co ``_TICK_SECONDS``: odczyt paczki plików umów i aneksów bez odczytu bieżącą
wersją czytnika (pierwszy bieg nadrabia całe teczki, ok. 1200 plików), potem
przeliczenie różnic wszystkich kontraktów z odczytami (harmonogram zmieniają
też ludzie), a przy ``CONTRACT_RATE_DOCS_AUTO_APPLY`` wpis różnic kategorii
``auto``. Każdy plik i każdy wpis we własnej transakcji — jeden zły plik nie
zatrzymuje reszty. ``CONTRACT_RATE_DOCS_READ_ENABLED=false`` wyłącza pętlę.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.contract_rate_documents import service

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 180
_TICK_SECONDS = 600
_BATCH = 25


async def run_cycle() -> dict[str, int]:
    stats = {"read": 0, "failed": 0, "refreshed": 0, "auto_applied": 0}
    async with AsyncSessionLocal() as db:
        pending = await service.pending_documents(db, _BATCH)
    for doc in pending:
        async with AsyncSessionLocal() as db:
            try:
                row = await service.read_document_row(db, doc)
                await db.commit()
                stats["read" if row.status == "read" else "failed"] += 1
            except Exception:  # noqa: BLE001 — jeden plik nie zatrzymuje paczki
                await db.rollback()
                stats["failed"] += 1
                logger.exception("contract_rate_documents: plik %s", doc.id)
    async with AsyncSessionLocal() as db:
        contract_ids = await service.contracts_with_reads(db)
    for contract_id in contract_ids:
        async with AsyncSessionLocal() as db:
            try:
                await service.refresh_contract(db, contract_id)
                await db.commit()
                stats["refreshed"] += 1
            except Exception:  # noqa: BLE001
                await db.rollback()
                logger.exception("contract_rate_documents: kontrakt %s", contract_id)
    if settings.CONTRACT_RATE_DOCS_AUTO_APPLY:
        async with AsyncSessionLocal() as db:
            candidates = [
                row.id
                for row in await service.open_findings(db)
                if row.decision is None
                and (row.finding or {}).get("category") == "auto"
            ]
        for read_id in candidates:
            async with AsyncSessionLocal() as db:
                try:
                    await service.apply_read(db, read_id, user=None)
                    await db.commit()
                    stats["auto_applied"] += 1
                except service.RateDocumentError as exc:
                    await db.rollback()
                    logger.info(
                        "contract_rate_documents: pominięty odczyt %s (%s)",
                        read_id,
                        exc,
                    )
                except Exception:  # noqa: BLE001
                    await db.rollback()
                    logger.exception(
                        "contract_rate_documents: wpis odczytu %s", read_id
                    )
    return stats


async def contract_rate_documents_loop() -> None:
    if not settings.CONTRACT_RATE_DOCS_READ_ENABLED:
        logger.info("contract_rate_documents_loop disabled")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "contract_rate_documents", max_silence_seconds=_TICK_SECONDS + 3 * 3600
    )
    while True:
        beat.tick()
        try:
            stats = await run_cycle()
            if any(stats.values()):
                logger.info("contract_rate_documents: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("contract_rate_documents: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
