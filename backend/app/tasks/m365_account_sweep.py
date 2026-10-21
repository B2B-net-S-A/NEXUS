"""Pętla: konto NEXUSA idzie za kontem Microsoft 365 (decyzja Artura 22.10.2026).

Co ``INTERVAL_SECONDS`` przebieg ``app.services.m365_account_sweep.run_once``.
Celowo poza ``hr_loops`` — nie zależy od ``HR_PROGRAM_ENABLED`` ani
``HR_LOOPS_ENABLED``, bo pilnuje dostępu do danych, nie modułu kadrowego.
Kończy się przed pierwszym przebiegiem przy ``M365_ACCOUNT_SWEEP_MODE=off``.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.m365_account_sweep import current_mode, run_once

logger = logging.getLogger(__name__)

#: Cztery przebiegi na dobę — kilkadziesiąt odczytów Graph za każdym razem.
INTERVAL_SECONDS = 6 * 3600


async def m365_account_sweep_loop() -> None:
    if current_mode() == "off":
        logger.info("m365_account_sweep disabled (M365_ACCOUNT_SWEEP_MODE=off)")
        return
    beat = loop_heartbeat.register(
        "m365_account_sweep", max_silence_seconds=INTERVAL_SECONDS + 1800
    )
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                result = await run_once(db)
            if result.get("planned") or result.get("errors"):
                logger.info("m365_account_sweep done %s", result)
        except Exception:  # noqa: BLE001 — jedno złe przejście nie zabija pętli
            logger.exception("m365_account_sweep failed")
        await asyncio.sleep(INTERVAL_SECONDS)
