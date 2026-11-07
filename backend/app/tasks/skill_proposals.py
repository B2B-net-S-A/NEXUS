"""Nocne propozycje do słownika umiejętności — raz na dobę, 1:00–5:00 (Warszawa).

Decyzja Artura z 06.11.2026 („Etap 1: A + B”): model co noc proponuje hasła
i warianty spoza słownika (``services/skill_proposals``), a rano Head of
Recruitment zatwierdza je w zakładce „Propozycje”. Dzień ostatniego biegu leży
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
from app.services import loop_heartbeat, skill_proposals, skill_relations

logger = logging.getLogger(__name__)

STATE_KEY = "skill_proposals_state"
_START_DELAY_SECONDS = 600
_CHECK_SECONDS = 1800
_NIGHT_HOURS = range(1, 5)


def in_night_window() -> bool:
    return local_now().hour in _NIGHT_HOURS


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
        summary = await skill_proposals.run(db)
        # Decyzja Artura z 07.11.2026: „pewne” propozycje i powiązania
        # zatwierdza nocny bieg, bez klikania (HoR+ może wycofać).
        summary["auto_accepted"] = await skill_proposals.accept_sure(
            db, curated_by=skill_relations.AUTO_CURATOR
        )
        summary["relations"] = await skill_relations.run(db)
        await _stamp(db, summary)
    return True


async def skill_proposals_loop() -> None:
    beat = loop_heartbeat.register(
        "skill_proposals", max_silence_seconds=_START_DELAY_SECONDS + 4 * _CHECK_SECONDS
    )
    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — zadanie tła nie może paść
            logger.exception("skill_proposals_loop iteration failed")
        await asyncio.sleep(_CHECK_SECONDS)
