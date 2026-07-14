"""Background loop — KPI Coach nudger.

Co `settings.KPI_COACH_LOOP_INTERVAL_SECONDS` sekund woła
`kpi_coach_service.run_scheduled_sweep()`, które ocenia operacyjnych
rekruterów i emituje praise/remind/eod_summary jeśli trzeba.

Pętla nigdy sama nie decyduje o emisji — całą logikę ma service.
Zadanie loopa to timer + isolated DB session per iteracja + error
containment (pojedyncza wyjątkowa iteracja nie zabija pętli).

Wzorzec oparty na `app/services/notification_triggers.notification_triggers_loop`
i `app/tasks/contract_alerts.contract_alerts_loop`.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.kpi_coach_service import (
    kpi_coach_nudge_mode,
    run_scheduled_sweep,
)

logger = logging.getLogger(__name__)


async def kpi_coach_nudger_loop() -> None:
    """Entry-point zarejestrowany w `app/main.py` lifespan."""
    mode = kpi_coach_nudge_mode()
    if mode == "off":
        logger.info("kpi_coach_nudger_loop disabled (mode=off)")
        return

    interval = max(60, settings.KPI_COACH_LOOP_INTERVAL_SECONDS)

    # Startup grace — daj DB/Qdrant dojść do formy przed pierwszym zapytaniem.
    await asyncio.sleep(60)

    logger.info("kpi_coach_nudger_loop started (interval=%ds mode=%s)", interval, mode)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                counters = await run_scheduled_sweep(db, dry_run=mode == "dry_run")
                if mode == "dry_run":
                    await db.rollback()
                else:
                    await db.commit()
                if any(counters.get(k, 0) for k in ("praise", "remind", "eod")):
                    logger.info("kpi_coach sweep: %s", counters)
                else:
                    logger.debug("kpi_coach sweep: %s", counters)
        except asyncio.CancelledError:
            logger.info("kpi_coach_nudger_loop cancelled")
            raise
        except Exception:
            logger.exception("kpi_coach_nudger_loop: iteration failed")
        await asyncio.sleep(interval)
