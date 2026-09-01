"""Dobowy przebieg dziennika seniority.

Po co pętla, skoro poziom liczy się przy odczycie: zmiana poziomu nie ma
własnego zdarzenia. Wynika z historii atrybucji, a ta bywa przepisywana przez
import — nie ma requestu, w którym dałoby się to zauważyć. Ktoś musi
OBSERWOWAĆ regularnie, żeby porównanie „przed / po" w ogóle istniało.

Uzasadnienie samego dziennika (i tego, czego on świadomie nie robi) siedzi
w `app/services/insights_seniority_journal.py` — nie powielam go tutaj, żeby
dwie kopie nie rozjechały się przy pierwszej zmianie.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.insights_seniority_journal import record_seniority_observations

logger = logging.getLogger(__name__)


async def run_once() -> dict:
    async with AsyncSessionLocal() as db:
        return await record_seniority_observations(db)


async def insights_seniority_journal_loop() -> None:
    """Kill-switch sprawdzany PRZED pętlą, nie w środku.

    Wyłączona funkcja ma nie budzić procesu co dobę po to, żeby sprawdzić tę
    samą flagę (ten sam błąd naprawiano w pętli CloudTalka i w `dl_alerts`).
    """
    if not settings.INSIGHTS_SENIORITY_JOURNAL_ENABLED:
        logger.info(
            "insights_seniority_journal_loop disabled "
            "(INSIGHTS_SENIORITY_JOURNAL_ENABLED=false)"
        )
        return
    interval = (
        max(1.0, float(settings.INSIGHTS_SENIORITY_JOURNAL_INTERVAL_HOURS)) * 3600
    )
    while True:
        try:
            summary = await run_once()
            # Logujemy TYLKO przebiegi, które coś zapisały. Dobowy wpis
            # „0 zmian" zamieniłby log w szum, w którym realna regresja ginie.
            if summary.get("inserted"):
                logger.info("insights seniority journal: %s", summary)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("insights_seniority_journal_loop iteration failed")
        await asyncio.sleep(interval)
