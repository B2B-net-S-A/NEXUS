"""Pętla dziennej kontroli zakresu aplikacji prepów (0510) — reguły w ``services``."""

from __future__ import annotations

import asyncio
import logging
import os

from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services.teams_prep_scope import scan_once

logger = logging.getLogger(__name__)

# Co 6 h; dzienny dedup `emit` pilnuje, że admin dostaje najwyżej jeden alarm
# na dobę, a restart po deployu nie czeka doby na pierwszą kontrolę.
CHECK_INTERVAL_SECONDS = max(
    600, int(os.environ.get("TEAMS_PREP_SCOPE_INTERVAL_SECONDS", str(6 * 3600)))
)


def enabled() -> bool:
    return (
        os.environ.get("TEAMS_PREP_SCOPE_ALERTS_ENABLED", "true").strip().lower()
        != "false"
    )


async def teams_prep_scope_alerts_loop() -> None:
    if not enabled():
        logger.info(
            "teams_prep_scope: disabled (TEAMS_PREP_SCOPE_ALERTS_ENABLED=false)"
        )
        return
    beat = loop_heartbeat.register(
        "teams_prep_scope_alerts",
        max_silence_seconds=CHECK_INTERVAL_SECONDS * 3 + 600,
    )
    # Po deployu nie ścigamy się z resztą pętli o połączenia.
    await asyncio.sleep(300)
    while True:
        beat.tick()
        try:
            async with AsyncSessionLocal() as db:
                sent = await scan_once(db)
            if sent:
                logger.info("teams_prep_scope: %s notifications", sent)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("teams_prep_scope: scan failed; next run retries")
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)
