"""Nocna pętla odpisu KRS spółki dla Rady nadzorczej (R1).

Raz na dobę (05:40 Warszawa) i raz przy starcie: pobiera odpis pełny,
zapisuje go, gdy treść się zmieniła, zakłada wiersze dokumentów z wzmianek
i daje dzwonek Radzie i adminom o każdym nowym wpisie. Pierwszy odpis
w bazie nie daje dzwonka (to stan zastany, nie zmiana). Przebieg jest
idempotentny: ten sam odpis to tylko nowa data sprawdzenia.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import seconds_until_local_time
from app.services import loop_heartbeat
from app.services.board import krs as krs_service
from app.services.board.notify import notify_new_entries

logger = logging.getLogger(__name__)


async def run_once() -> None:
    krs = krs_service.company_krs()
    try:
        payload = await krs_service.fetch_full_extract(krs)
    except Exception as exc:  # noqa: BLE001 — API KRS bywa niedostępne; zostaje ostatni odpis
        logger.warning("board_krs: odpis KRS niedostępny (%s)", type(exc).__name__)
        return
    async with AsyncSessionLocal() as db:
        try:
            result = await krs_service.store_extract(db, payload)
            if result.new_entries:
                await notify_new_entries(db, result.snapshot_id, result.new_entries)
            await db.commit()
        except Exception:
            await db.rollback()
            raise
    logger.info(
        "board_krs: odpis %s, zmiana=%s, nowe wpisy=%d, nowe dokumenty=%d",
        krs,
        result.changed,
        len(result.new_entries),
        result.documents_created,
    )


async def board_krs_loop() -> None:
    if not settings.BOARD_KRS_ENABLED:
        logger.info("board_krs_loop disabled (BOARD_KRS_ENABLED=false)")
        return
    beat = loop_heartbeat.register("board_krs", max_silence_seconds=27 * 3600)
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("board_krs_loop iteration failed")
        delay = seconds_until_local_time(
            datetime.now(timezone.utc),
            settings.BOARD_KRS_RUN_HOUR_LOCAL,
            settings.BOARD_KRS_RUN_MINUTE_LOCAL,
        )
        await asyncio.sleep(max(delay, 60.0))
