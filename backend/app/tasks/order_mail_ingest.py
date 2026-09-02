"""Pętla pobierania zamówień z maila — dwa sloty dobowe w czasie lokalnym.

Wzorzec ``traffit_sync``: kill-switch PRZED pętlą (wyłączona integracja nie
budzi procesu, żeby sprawdzić tę samą flagę), sesja per tick, watermark
w bazie (Coolify restartuje kontener przy każdym pushu na main — timer
w pamięci startowałby od zera). Predykat ``due_slot`` jest czysty i testowalny.

Dlaczego JEDEN marker i sloty, a nie dwa markery z ``should_run_daily``:
z ``min_gap≈10 h`` i semantyką „godzina ≥ H i odstęp ≥ gap" marker poranny
byłby należny ponownie o 18:00 tego samego dnia (18 ≥ 8, odstęp 10 h) — trzeci
bieg. Sloty w czasie LOKALNYM (Europe/Warsaw), bo ticket mówi „ok. 8:00
i 15:00", a ``*_HOUR_UTC`` rozjeżdża się z DST.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.scheduling import DEFAULT_TZ
from app.services.order_mail_ingest import read_state, run_order_mail_ingest

logger = logging.getLogger(__name__)

_CHECK_INTERVAL_SECONDS = 300


def parse_slots(raw: str) -> list[time]:
    slots: list[time] = []
    for chunk in (raw or "").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            hh, mm = chunk.split(":")
            slots.append(time(int(hh), int(mm)))
        except ValueError:
            logger.warning("order_mail: ignoring malformed slot %r", chunk)
    return sorted(set(slots))


def due_slot(
    now_local: datetime,
    last_finished_local: Optional[datetime],
    slots: list[time],
) -> bool:
    """Czy między ostatnim biegiem a teraz zaczął się któryś slot.

    Pierwszy bieg (brak watermarku) — od razu. Potem: raz, gdy początek
    dowolnego slotu (dziś albo wczoraj — restart o 07:59 nie może zgubić 08:00)
    leży w przedziale ``(last_finished, now]``. Bieg, który sam przeciągnął
    się przez slot, NIE odpala drugiego natychmiast, bo ``last_finished``
    stoi już za tym slotem.
    """
    if not slots:
        return False
    if last_finished_local is None:
        return True
    for day in (now_local.date(), now_local.date() - timedelta(days=1)):
        for slot in slots:
            start = datetime.combine(day, slot, tzinfo=now_local.tzinfo)
            if last_finished_local < start <= now_local:
                return True
    return False


async def order_mail_ingest_loop() -> None:
    if not settings.ORDER_MAIL_INGEST_ENABLED:
        logger.info("order_mail_ingest_loop disabled (ORDER_MAIL_INGEST_ENABLED=false)")
        return
    tz = ZoneInfo(DEFAULT_TZ)
    slots = parse_slots(settings.ORDER_MAIL_SLOTS_LOCAL)
    logger.info(
        "order_mail_ingest_loop started (slots %s %s)",
        [s.strftime("%H:%M") for s in slots],
        DEFAULT_TZ,
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
            now_local = datetime.now(tz)
            if due_slot(now_local, last.astimezone(tz) if last else None, slots):
                await run_order_mail_ingest(reason="scheduled")
        except asyncio.CancelledError:
            logger.info("order_mail_ingest_loop cancelled — shutting down")
            raise
        except Exception:  # noqa: BLE001
            logger.exception("order_mail_ingest_loop iteration failed")
        await asyncio.sleep(_CHECK_INTERVAL_SECONDS)
