"""Pętla przeglądu zgłoszeń z linku rekrutacji (0404) — co 30 s.

Bierze oczekujące oceny (``FOR UPDATE SKIP LOCKED`` + dzierżawa), ocenia je
i decyduje: „Nowi” albo „Odrzuceni przez AI”. Rano wysyła skrót odrzuconych.

Pętla biegnie także przy ``APPLICATION_SCREENING_ENABLED=false``: nowe
zgłoszenia idą wtedy od razu do „Nowi” (jak przed 0404), a oceny złożone
przed wyłączeniem pętla dodaje bez modelu („AI nie oceniło”). Wyłączenie nie
może zostawić ludzi w zawieszeniu. Zapytanie przy pustej kolejce to jeden
indeks częściowy (``ix_application_screenings_pending``).
"""

from __future__ import annotations

import asyncio
import logging

from app.services import loop_heartbeat
from app.services.application_screening import run_once

logger = logging.getLogger(__name__)

_INITIAL_DELAY_SECONDS = 60
_INTERVAL_SECONDS = 30


async def application_screening_loop() -> None:
    """Rejestrowana w lifespanie ``main.py``."""
    await asyncio.sleep(_INITIAL_DELAY_SECONDS)
    # Jeden przebieg to najwyżej kilka wywołań modelu; 15 min ciszy = zawieszenie.
    beat = loop_heartbeat.register("application_screening", max_silence_seconds=900)
    while True:
        beat.tick()
        try:
            stats = await run_once()
            if stats:
                logger.info("application_screening: %s", stats)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            logger.exception("application_screening: cykl padł")
        await asyncio.sleep(_INTERVAL_SECONDS)
