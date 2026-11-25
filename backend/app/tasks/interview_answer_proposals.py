"""Nocne propozycje odpowiedzi w „Pytaniach z rozmów” — raz na dobę od 02:40 (Warszawa).

Decyzja Artura z 25.11.2026: odpowiedzi AI dla pytań z banku klienta liczą się
hurtem w nocy (``services/interview_answer_proposals``, F55), do
``INTERVIEW_ANSWER_PROPOSALS_PER_NIGHT`` pytań na noc. Okno 02:40–05:00 nie
zachodzi na start propozycji słownika (01:00); dzień ostatniego biegu leży
w ``app_settings``, więc restart przy deployu nie liczy drugi raz tej samej nocy.
"""

from __future__ import annotations

import asyncio
import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import AsyncSessionLocal
from app.core.scheduling import business_today, local_now
from app.models.app_setting import AppSetting
from app.services import interview_answer_proposals, loop_heartbeat

logger = logging.getLogger(__name__)

STATE_KEY = "interview_answer_proposals_state"
_START_DELAY_SECONDS = 600
_CHECK_SECONDS = 900
_WINDOW_START = (2, 40)
_WINDOW_END_HOUR = 5


def in_night_window() -> bool:
    now = local_now()
    return _WINDOW_START <= (now.hour, now.minute) and now.hour < _WINDOW_END_HOUR


async def _ran_today(db) -> bool:
    value = await db.scalar(select(AppSetting.value).where(AppSetting.key == STATE_KEY))
    return (value or {}).get("last_run_on") == business_today().isoformat()


async def _stamp(db, summary: dict) -> None:
    value = {"last_run_on": business_today().isoformat(), "summary": summary}
    await db.execute(
        insert(AppSetting)
        .values(key=STATE_KEY, value=value)
        .on_conflict_do_update(index_elements=[AppSetting.key], set_={"value": value})
    )
    await db.commit()


async def run_once() -> bool:
    """Jeden bieg nocy; ``False`` = poza oknem albo już dziś liczone."""
    if not in_night_window():
        return False
    async with AsyncSessionLocal() as db:
        if await _ran_today(db):
            return False
        summary = await interview_answer_proposals.run(db)
        await _stamp(db, summary)
    return True


async def interview_answer_proposals_loop() -> None:
    beat = loop_heartbeat.register(
        "interview_answer_proposals",
        max_silence_seconds=_START_DELAY_SECONDS + 4 * _CHECK_SECONDS,
    )
    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — zadanie tła nie może paść
            logger.exception("interview_answer_proposals_loop iteration failed")
        await asyncio.sleep(_CHECK_SECONDS)
