"""Mapa słownika aktualna w każdym procesie (audyt 2, W5, 08.11.2026).

Słownik i mapa wiedzy żyją w pamięci procesu. Co minutę jedno lekkie zapytanie
o ``app_settings['skill_dictionary_version']``, a przy zmianie przeładowanie
mapy. Pętla biegnie też w procesie bez blokady lidera, dlatego w ``main.py``
stoi poza rejestrem ``app.state.background_tasks``. Na stagingu jest bezpieczna:
tylko czyta bazę.
"""

from __future__ import annotations

import asyncio
import logging

from app.services.skill_taxonomy_loader import sync_dictionary_version

logger = logging.getLogger(__name__)

POLL_SECONDS = 60


async def skill_dictionary_sync_loop() -> None:
    while True:
        await asyncio.sleep(POLL_SECONDS)
        try:
            count = await sync_dictionary_version()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 — zadanie tła nie może paść
            logger.exception("skill_dictionary_sync iteration failed")
            continue
        if count is not None:
            logger.info("Skill alias map reloaded after version change: %d", count)
