"""Link do Pracuj.pl z maila Pracuj.pl — co 10 minut (26.11.2026).

Przegląda maile ``extranet@pracuj.pl`` „Publikacja ogłoszenia na …” z ostatnich
``pracuj_inbox.SCAN_WINDOW`` dni, które synchronizacja skrzynek już zapisała
w ``emails``, i oznacza Pracuj.pl przy pewnym dopasowaniu
(``services/job_ad/pracuj_inbox.py``). Niepewne dopasowania okno pokazuje jako
propozycję — pętla ich nie rusza. Sama baza, bez wołań na zewnątrz, więc na
stagingu działa i da się ją przeklikać.

Przebieg jest idempotentny: oznaczona rekrutacja wypada z kandydatów, a link
w użyciu wypada z maili. Każde oznaczenie we własnej transakcji.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.database import AsyncSessionLocal
from app.services.job_ad import pracuj_inbox

logger = logging.getLogger(__name__)

_START_DELAY_SECONDS = 120
_CHECK_SECONDS = 600


async def run_once(now: datetime | None = None) -> int:
    """Jeden przebieg; zwraca liczbę oznaczonych rekrutacji."""
    moment = now or datetime.now(timezone.utc)
    async with AsyncSessionLocal() as db:
        planned = await pracuj_inbox.plan(
            db, await pracuj_inbox.recent_mails(db, now=moment)
        )
    linked = 0
    for item in planned:
        if item.match.auto is None:
            continue
        async with AsyncSessionLocal() as db:
            try:
                if await pracuj_inbox.link_auto(db, item.match.auto, item.mail):
                    linked += 1
                await db.commit()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 — jedna rekrutacja nie zatrzymuje reszty
                await db.rollback()
                logger.exception(
                    "pracuj mail links: job=%s email=%s failed",
                    item.match.auto,
                    item.mail.email_id,
                )
    if linked:
        logger.info("pracuj mail links: %s ads linked from Pracuj.pl mail", linked)
    return linked


async def pracuj_mail_links_loop() -> None:
    await asyncio.sleep(_START_DELAY_SECONDS)
    while True:
        try:
            await run_once()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — zadanie tła nie może paść
            logger.exception("pracuj mail links: pass failed")
        await asyncio.sleep(_CHECK_SECONDS)
