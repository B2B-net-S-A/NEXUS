"""Pętla pobierania zamówień z maila — co ``ORDER_MAIL_POLL_INTERVAL_MINUTES``.

Wzorzec ``traffit_sync``: kill-switch PRZED pętlą (wyłączona integracja nie
budzi procesu, żeby sprawdzić tę samą flagę), sesja per tick, watermark
w bazie (Coolify restartuje kontener przy każdym pushu na main — timer
w pamięci startowałby od zera). Predykat ``due_interval`` jest czysty i testowalny.

Dlaczego odstęp, a nie sloty dobowe (08:00/15:00 do 09.2026): zamówienie,
które przyszło o 08:37, czekało na slot 15:00, a „sprawdź teraz" istniało
wyłącznie jako endpoint admina. Odstęp liczy się od KOŃCA ostatniego biegu:
bieg ręczny przesuwa zegar (nie ma dwóch biegów tuż po sobie), a bieg
przerwany restartem końca NIE zapisuje, więc po starcie kontenera jest
należny od razu — to ta ścieżka sprawia, że zamówienie czekające w skrzynce
jest pobierane zaraz po deployu, nie za godzinę.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.services.order_mail_ingest import (
    poll_interval_minutes,
    read_state,
    run_order_mail_ingest,
)

logger = logging.getLogger(__name__)

# Tick pętli: przy odstępie liczonym w minutach minuta zwłoki nie ma znaczenia,
# a jedno sprawdzenie to SELECT jednowierszowego stanu.
_CHECK_INTERVAL_SECONDS = 60


def due_interval(
    now: datetime, last_finished: Optional[datetime], interval: timedelta
) -> bool:
    """Czy od końca ostatniego biegu minął cały odstęp.

    Brak watermarku — od razu: to pierwszy bieg albo bieg przerwany, który
    końca nie zapisał (restart kontenera w trakcie). Bieg trwający właśnie
    teraz nie jest tu widoczny — odrzuca go blokada w ``run_order_mail_ingest``.
    """
    if last_finished is None:
        return True
    return now - last_finished >= interval


async def order_mail_ingest_loop() -> None:
    if not settings.ORDER_MAIL_INGEST_ENABLED:
        logger.info("order_mail_ingest_loop disabled (ORDER_MAIL_INGEST_ENABLED=false)")
        return
    logger.info(
        "order_mail_ingest_loop started (every %s min)", poll_interval_minutes()
    )
    await asyncio.sleep(90)  # bootstrap grace, staggered vs. other loops
    while True:
        try:
            if not settings.ORDER_MAIL_INGEST_ENABLED:
                await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
                continue
            async with AsyncSessionLocal() as db:
                state = await read_state(db)
            last = (state or {}).get("last_run_finished_at")
            if last is not None and last.tzinfo is None:
                last = last.replace(tzinfo=timezone.utc)
            interval = timedelta(minutes=poll_interval_minutes())
            if due_interval(datetime.now(timezone.utc), last, interval):
                await run_order_mail_ingest(reason="scheduled")
        except asyncio.CancelledError:
            logger.info("order_mail_ingest_loop cancelled — shutting down")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("order_mail_ingest_loop iteration failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
