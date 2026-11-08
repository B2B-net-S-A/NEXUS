"""Pętla P0 po terminie — co 5 minut, dzwoni 7:00–20:00 (Warszawa).

Prośba Olafa z 06.11.2026: P0 po terminie trwa, dopóki Head of Recruitment
nie wybierze „Przedłuż o 24 h” albo „Zakończ P0”. Pętla tylko o tym
przypomina — raz na termin rekrutacji (``services/job_p0.notify_overdue``),
więc restart przy deployu niczego nie wysyła drugi raz. Termin, który minął
w nocy, dzwoni o 7:00.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.core.scheduling import local_now
from app.services import loop_heartbeat
from app.services.job_p0 import notify_overdue

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 300
_FIRST_HOUR = 7
_LAST_HOUR = 20


def in_ringing_hours() -> bool:
    return _FIRST_HOUR <= local_now().hour < _LAST_HOUR


async def job_p0_overdue_loop() -> None:
    beat = loop_heartbeat.register(
        "job_p0_overdue", max_silence_seconds=6 * _INTERVAL_SECONDS
    )
    while True:
        beat.tick()
        if in_ringing_hours():
            try:
                async with AsyncSessionLocal() as db:
                    sent = await notify_overdue(db)
                if sent:
                    logger.info("job_p0_overdue: %s dzwonków", sent)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("job_p0_overdue_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
