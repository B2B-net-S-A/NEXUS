"""Pętla kart bez śladu — co 15 minut, tylko w dzień roboczy.

Reguła i przebieg: ``services/screening_stale.py``. W dzień roboczy od 8:00
raz dziennie także ostrzeżenie o kartach, które wrócą następnego dnia
roboczego (26.11.2026). Karta wraca w dniu
powrotu przy pierwszym przebiegu po północy (przed blokadą porcji o 7:00),
a dedup dobowy dzwonka sprawia, że restart przy deployu nie dzwoni drugi raz.
Na stagingu zatrzymana (kopia produkcji, wspólna baza sesji): ręcznie
``python -m scripts.screening_stale_return``.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from app.core.config import settings
from app.services import loop_heartbeat
from app.core.scheduling import business_date
from app.services.screening_stale import run_once_safely, warn_due, warn_once_safely

logger = logging.getLogger(__name__)

_INTERVAL_SECONDS = 15 * 60


async def screening_stale_loop() -> None:
    # Weekend i święta przebieg kończy od razu, więc heartbeat bije i wtedy.
    beat = loop_heartbeat.register(
        "screening_stale", max_silence_seconds=4 * _INTERVAL_SECONDS
    )
    # Poranne ostrzeżenie (26.11.2026) raz dziennie od 8:00. `warned_on` oszczędza
    # przeliczeń; po restarcie dzisiejszy dzwonek w bazie zostaje bez zmian
    # (`refresh=False`), więc drugi raz nie dzwoni.
    warned_on = None
    while True:
        beat.tick()
        if settings.SCREENING_STALE_RETURN_ENABLED:
            try:
                await run_once_safely()
                now = datetime.now(timezone.utc)
                if warned_on != business_date(now) and warn_due(now):
                    if await warn_once_safely(now) is not None:
                        warned_on = business_date(now)
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                logger.exception("screening_stale_loop iteration failed")
        await asyncio.sleep(_INTERVAL_SECONDS)
