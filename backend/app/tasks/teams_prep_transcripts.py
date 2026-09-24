"""Pętla pobierania transkryptów prepów z Teams (0369).

Wyłącznik ``TEAMS_PREP_TRANSCRIPTS_ENABLED`` (domyślnie OFF) — wyłączona
pętla kończy się PRZED ``while True``. Stan wiersza (kolejka) żyje w bazie,
więc restart kontenera przy deployu niczego nie gubi.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.prep_transcripts import run_once

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 150


def _interval_seconds() -> int:
    return max(120, int(settings.TEAMS_PREP_POLL_MINUTES) * 60)


async def teams_prep_transcripts_loop() -> None:
    if not settings.TEAMS_PREP_TRANSCRIPTS_ENABLED:
        logger.info(
            "teams_prep_transcripts_loop disabled (TEAMS_PREP_TRANSCRIPTS_ENABLED=false)"
        )
        return
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    beat = loop_heartbeat.register(
        "teams_prep_transcripts", max_silence_seconds=_interval_seconds() + 3600
    )
    while True:
        beat.tick()
        try:
            if settings.TEAMS_PREP_TRANSCRIPTS_ENABLED:
                async with AsyncSessionLocal() as db:
                    stats = await run_once(db)
                if stats.checked or stats.cancelled:
                    logger.info(
                        "teams_prep_transcripts: checked=%s fetched=%s missing=%s "
                        "waiting=%s forbidden=%s errors=%s cancelled=%s",
                        stats.checked,
                        stats.fetched,
                        stats.missing,
                        stats.waiting,
                        stats.forbidden,
                        stats.errors,
                        stats.cancelled,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("teams_prep_transcripts: cykl padł")
        await asyncio.sleep(_interval_seconds())
