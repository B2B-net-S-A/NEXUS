"""Pętla odświeżania korpusu prawa asystenta prawnego (kontener worker), co godzinę.

Akt, którego ostatnie sprawdzenie (``legal_acts.checked_at``) jest starsze
niż ``RECHECK_AFTER`` albo go nie było, przechodzi przez ``corpus.refresh_act``:
pytanie o najnowszy tekst jednolity (ELI) albo wersję skonsolidowaną
(CELLAR), a gdy jest nowa — pobranie, podział na jednostki, zapis wersji
z listą zmian (zdarzenie dla Przepisów, część H) i wektory. Pierwszy bieg po
wdrożeniu zasila cały korpus (16 aktów, kilka minut; PDF-y czyta osobny
proces). Nieudane sprawdzenie zostawia poprzednią wersję i ponawia się po
``RETRY_FAILED_AFTER``.

Wyłącznik ``LEGAL_CORPUS_REFRESH_ENABLED`` sprawdzany przed pętlą. Na stagingu
pętla stoi (``STAGING_BLOCKED_TASKS``: API Sejmu i Urzędu Publikacji UE),
a korpus zasila tam ``scripts/legal_corpus_seed.py``.
→ docs/claude/asystent-prawny/fundament-korpus-prawa-weryfikator-cytatow.md
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.models.legal_corpus import LegalAct
from app.services import loop_heartbeat
from app.services.legal import corpus, fetch
from app.services.legal.acts import ACTS, ActSpec

logger = logging.getLogger(__name__)

TICK_SECONDS = 60 * 60
START_DELAY_SECONDS = 5 * 60
RECHECK_AFTER = timedelta(hours=20)
RETRY_FAILED_AFTER = timedelta(hours=2)


def due(
    checked_at: Optional[datetime], status: Optional[str], *, now: datetime
) -> bool:
    """Czy akt czeka na sprawdzenie (czyste)."""
    if checked_at is None:
        return True
    wait = RETRY_FAILED_AFTER if status == "failed" else RECHECK_AFTER
    return now - checked_at >= wait


async def due_specs(now: datetime) -> list[ActSpec]:
    async with AsyncSessionLocal() as db:
        await corpus.ensure_acts(db)
        await db.commit()
        rows = (
            await db.execute(
                select(LegalAct.key, LegalAct.checked_at, LegalAct.fetch_status)
            )
        ).all()
    state = {key: (checked, status) for key, checked, status in rows}
    return [spec for spec in ACTS if due(*state.get(spec.key, (None, None)), now=now)]


async def tick(now: datetime) -> dict[str, int]:
    counts = {"checked": 0, "new_version": 0, "failed": 0}
    specs = await due_specs(now)
    if not specs:
        return counts
    async with fetch.client() as http:
        for spec in specs:
            result = await corpus.refresh_act(spec, http=http)
            counts["checked"] += 1
            if result.status in counts:
                counts[result.status] += 1
    return counts


async def legal_corpus_loop() -> None:
    if not settings.LEGAL_CORPUS_REFRESH_ENABLED:
        logger.info("legal_corpus_loop disabled")
        return
    beat = loop_heartbeat.register("legal_corpus", max_silence_seconds=4 * TICK_SECONDS)
    await asyncio.sleep(START_DELAY_SECONDS)
    while True:
        beat.tick()
        try:
            counts = await tick(datetime.now(timezone.utc))
            if counts["checked"]:
                logger.info(
                    "legal_corpus tick checked=%d new_version=%d failed=%d",
                    counts["checked"],
                    counts["new_version"],
                    counts["failed"],
                )
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("legal_corpus_loop iteration failed")
        await asyncio.sleep(TICK_SECONDS)
