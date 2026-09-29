"""Pętla dokumentów kontraktów z SharePointa (ticket 9, 0402).

Bez poświadczeń rejestracji „NEXUS Contract Documents” kończy się PRZED
``while True``. Z poświadczeniami: co minutę podejmuje przebiegi pierwszego
pobrania przerwane deployem (dzierżawa w bazie), a przy
``CONTRACT_DOCS_SP_SYNC_ENABLED`` co ``CONTRACT_DOCS_SP_SYNC_MINUTES``
synchronizuje folder w obie strony.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.contract_folder_docs.service import resume_interrupted
from app.services.contract_folder_docs.sync import (
    run_sync,
    sync_due,
    sync_interval_seconds,
)
from app.services.m365.sharepoint_docs import credentials_configured

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 120
_TICK_SECONDS = 60


async def contract_docs_sharepoint_loop() -> None:
    if not credentials_configured():
        logger.info("contract_docs_sharepoint_loop disabled (no app registration)")
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    # Pobranie kilkuset plików z SharePointa to minuty, a bieg synchronizacji
    # może trafić na throttling — próg ciszy z zapasem kilku godzin.
    beat = loop_heartbeat.register(
        "contract_docs_sharepoint",
        max_silence_seconds=sync_interval_seconds() + 4 * 3600,
    )
    while True:
        beat.tick()
        try:
            resumed = await resume_interrupted()
            if resumed:
                logger.info("contract_docs_sharepoint: resumed runs=%s", resumed)
            if settings.CONTRACT_DOCS_SP_SYNC_ENABLED:
                async with AsyncSessionLocal() as db:
                    due = await sync_due(db)
                if due:
                    async with AsyncSessionLocal() as db:
                        stats = await run_sync(db)
                    if stats is not None:
                        logger.info(
                            "contract_docs_sharepoint: sync %s", stats.as_dict()
                        )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("contract_docs_sharepoint: cykl padł")
        await asyncio.sleep(_TICK_SECONDS)
