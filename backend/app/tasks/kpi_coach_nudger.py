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
from app.services.kpi_coach_service import run_scheduled_sweep

logger = logging.getLogger(__name__)


async def kpi_coach_nudger_loop() -> None:
    """Entry-point zarejestrowany w `app/main.py` lifespan."""
    # R0 (plan 2026-07-16): stary Coach liczy KPI z UserActivity (log
    # pomocniczy, nie kanoniczne metryki) — emisja nudge'y wstrzymana do
    # czasu KPI Coach v2 na danych ATS. Historia notyfikacji zostaje.
    if not settings.KPI_COACH_NUDGER_ENABLED:
        logger.info(
            "kpi_coach_nudger_loop disabled (KPI_COACH_NUDGER_ENABLED=false) — "
            "wznowienie po migracji na KPI Coach v2 (canonical ATS metrics)"
        )
        return

    interval = max(60, settings.KPI_COACH_LOOP_INTERVAL_SECONDS)

    # Startup grace — daj DB/Qdrant dojść do formy przed pierwszym zapytaniem.
    await asyncio.sleep(60)

    logger.info("kpi_coach_nudger_loop started (interval=%ds)", interval)

    while True:
        try:
            async with AsyncSessionLocal() as db:
                counters = await run_scheduled_sweep(db)
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
