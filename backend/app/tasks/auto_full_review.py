"""Pętla nocnego automatycznego przeglądu bazy (21.09.2026).

Cała logika jest w `services/auto_full_review.py`; tu tylko rytm. Pętla budzi
się co `AUTO_FULL_REVIEW_INTERVAL_SECONDS`, a w oknie nocnym zakłada najwyżej
jeden przegląd na tick — i tylko wtedy, gdy żaden inny nie czeka ani nie trwa.
Sam przegląd wykonuje istniejący worker `candidate_search`.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.services import loop_heartbeat

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 90


async def auto_full_review_loop() -> None:
    from app.services import auto_full_review

    if not auto_full_review.enabled():
        logger.info("[auto_full_review] disabled (AUTO_FULL_REVIEW_ENABLED=false)")
        return
    interval = max(30, int(settings.AUTO_FULL_REVIEW_INTERVAL_SECONDS))
    beat = loop_heartbeat.register(
        "auto_full_review", max_silence_seconds=interval + 1800
    )
    logger.info("[auto_full_review] loop started (interval=%ss)", interval)
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            outcome = await auto_full_review.tick()
            if outcome.get("started") or outcome.get("reconciled"):
                logger.info("[auto_full_review] %s", outcome)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001 — pętla nie może umrzeć
            logger.warning("[auto_full_review] tick failed: %s", type(exc).__name__)
        await asyncio.sleep(interval)
