"""Pętla prepów z Teams: transkrypty (0370) i odpowiedzi kandydatów (0453).

Transkrypty: wyłącznik ``TEAMS_PREP_TRANSCRIPTS_ENABLED`` (domyślnie OFF).
Odpowiedzi kandydata i zmiany z Outlooka (``prep_responses``, 17.10.2026):
gdy planowanie prepów działa (``prep_meetings.app_only_ready``). Pętla bez
żadnej z tych dwóch rzeczy kończy się PRZED ``while True``. Stan wiersza
(kolejka) żyje w bazie, więc restart kontenera przy deployu niczego nie gubi.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services import loop_heartbeat
from app.services import prep_meetings, prep_responses
from app.services.prep_transcripts import run_once
from app.services.followup_meetings import fetch_due as fetch_followup_transcripts

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 150


def _interval_seconds() -> int:
    return max(120, int(settings.TEAMS_PREP_POLL_MINUTES) * 60)


async def teams_prep_transcripts_loop() -> None:
    if not (settings.TEAMS_PREP_TRANSCRIPTS_ENABLED or prep_meetings.app_only_ready()):
        logger.info(
            "teams_prep_transcripts_loop disabled (TEAMS_PREP_TRANSCRIPTS_ENABLED=false, "
            "prep scheduling off)"
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
                    followup_fetched = await fetch_followup_transcripts(db)
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
                if followup_fetched:
                    logger.info("teams followups: fetched=%s", followup_fetched)
            if prep_meetings.app_only_ready():
                async with AsyncSessionLocal() as db:
                    responses = await prep_responses.sync_upcoming(db)
                if responses.changed or responses.errors:
                    logger.info(
                        "prep responses: checked=%s responses=%s moved=%s "
                        "cancelled=%s reminders=%s errors=%s",
                        responses.checked,
                        responses.responses,
                        responses.moved,
                        responses.cancelled,
                        responses.reminders,
                        responses.errors,
                    )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("teams_prep_transcripts: cykl padł")
        await asyncio.sleep(_interval_seconds())
