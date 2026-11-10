"""Kolejka „Kto już to robił”: jeden przebieg naraz, pusta kolejka nic nie kosztuje.

Przebieg trwa 1,5–2 min (rozbicie celu, pula, ok. 100 ocen CV). Dzierżawa
10 min: proces zabity w trakcie (u nas zwykle wdrożenie) oddaje przebieg
następnemu przejęciu, a po trzech próbach bez wyniku czwarte przejęcie kończy
go jako ``failed`` (``abandoned``),
żeby nie zajmował autorowi jednego z dwóch slotów w nieskończoność.
"""

import asyncio
import logging
import time

from app.core.database import AsyncSessionLocal
from app.models.duty_search_run import DutySearchRun
from app.services import duty_search, loop_heartbeat

logger = logging.getLogger(__name__)

POLL_SECONDS = 5
PURGE_EVERY_SECONDS = 3600


async def _run_one() -> bool:
    async with AsyncSessionLocal() as db:
        claimed = await duty_search.claim_next(db)
        if claimed is None:
            return False
        run_id, claims = claimed
        if claims > duty_search.MAX_CLAIMS:
            await duty_search.fail_run(db, run_id, "abandoned")
            logger.warning(
                "[duty-search] %s porzucony po %s przejęciach", run_id, claims - 1
            )
            return True
        run = await db.get(DutySearchRun, run_id)
        if run is None:
            return True
        try:
            await duty_search.execute_run(db, run)
            await db.commit()
            logger.info(
                "[duty-search] %s gotowy: %s", run_id, (run.metrics or {}).get("tiers")
            )
        except duty_search.DutySearchFailed as exc:
            await db.rollback()
            await duty_search.fail_run(db, run_id, exc.code)
            logger.warning("[duty-search] %s nieudany: %s", run_id, exc.code)
        except Exception:  # noqa: BLE001
            logger.exception("[duty-search] %s przerwany błędem", run_id)
            await db.rollback()
            await duty_search.fail_run(db, run_id, "error")
    return True


async def duty_search_loop():
    # Jeden przebieg trwa do kilku minut bez ticku; 30 min ciszy = pętla stoi.
    beat = loop_heartbeat.register("duty_search", max_silence_seconds=1800)
    last_purge = 0.0
    while True:
        beat.tick()
        try:
            if time.monotonic() - last_purge > PURGE_EVERY_SECONDS:
                async with AsyncSessionLocal() as db:
                    purged = await duty_search.purge_old(db)
                if purged:
                    logger.info(
                        "[duty-search] usunięto %s przebiegów starszych niż 30 dni",
                        purged,
                    )
                last_purge = time.monotonic()
            if await _run_one():
                continue
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("[duty-search] pętla: błąd")
        await asyncio.sleep(POLL_SECONDS)
