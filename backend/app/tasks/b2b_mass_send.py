"""Pętla masowej wysyłki nowej umowy B2B (E5b, 0756, worker).

Co ``_TICK_SECONDS``: najwyżej ``service.CHUNK`` pozycji biegnącej paczki —
każda we własnej transakcji: wiersz Generatora tą samą drogą co „Pobierz
DOCX”, potem wysyłka do podpisu i mail ze skrzynki osoby, która zaczęła
paczkę. Partie po 50 co 15 minut, żeby skrzynka M365 nie wpadła w limit.

Dwie blokady: ``B2B_MASS_SEND_ENABLED=false`` (domyślnie) kończy pętlę przy
starcie, a dopóki admin nie oznaczy nowego wzoru jako podpiętego
(``app_settings['b2b_mass_send']``), bieg nie robi nic — przełącznik czyta
się na początku biegu i jeszcze raz przed każdą pozycją i każdą wysyłką.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.b2b_mass_send import B2BMassSendBatch
from app.services import loop_heartbeat
from app.services.b2b_mass_send import service
from app.services.b2b_mass_send import settings as mass_settings

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 300
_TICK_SECONDS = 900


async def run_cycle(limit: int = service.CHUNK) -> dict[str, int]:
    stats: dict[str, int] = {}
    async with AsyncSessionLocal() as db:
        if not (await mass_settings.load(db)).template_ready:
            return {"blocked": 1}
        batch_ids = list(
            (
                await db.scalars(
                    select(B2BMassSendBatch.id)
                    .where(B2BMassSendBatch.status == "running")
                    .order_by(B2BMassSendBatch.id)
                )
            ).all()
        )
    left = limit
    for batch_id in batch_ids:
        async with AsyncSessionLocal() as db:
            item_ids = await service.next_item_ids(db, batch_id, left)
        for item_id in item_ids:
            async with AsyncSessionLocal() as db:
                try:
                    result = await service.process_item(db, item_id)
                except Exception:  # noqa: BLE001 — jedna osoba nie zatrzymuje paczki
                    await db.rollback()
                    logger.exception("b2b_mass_send: pozycja %s", item_id)
                    result = "error"
            if result is None:
                # Wysyłkę zablokowano w trakcie biegu albo paczka stanęła.
                return {**stats, "stopped": 1}
            stats[result] = stats.get(result, 0) + 1
            left -= 1
        async with AsyncSessionLocal() as db:
            await service.finish_if_done(db, batch_id)
        if left <= 0:
            break
    return stats


async def b2b_mass_send_loop() -> None:
    if not settings.B2B_MASS_SEND_ENABLED:
        logger.info("b2b_mass_send_loop disabled")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "b2b_mass_send", max_silence_seconds=_TICK_SECONDS + 3 * 3600
    )
    while True:
        beat.tick()
        try:
            stats = await run_cycle()
            if any(stats.values()):
                logger.info("b2b_mass_send: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("b2b_mass_send: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
