"""Przeliczenie QC CV po zmianie reguł — raz po starcie.

Plakietka QC na Tablicy czyta zapisany przebieg, a bramka ruchu liczy QC na
żywo. Po zmianie reguł (`cv_qc.QC_VERSION`) pary sprzed wysłania z przebiegiem
starszej wersji pokazywałyby stary stan, dopóki ktoś nie otworzy okna QC. Zadanie kończy się samo: przeliczony przebieg ma bieżącą
wersję, więc kolejny start nic nie znajduje.
"""

from __future__ import annotations

import asyncio
import logging

from app.core.database import AsyncSessionLocal
from app.services import cv_qc

logger = logging.getLogger(__name__)

# Start aplikacji ma pierwszeństwo — QC czyta pliki CV z magazynu.
_START_DELAY_SECONDS = 90


async def cv_qc_recompute_loop() -> None:
    await asyncio.sleep(_START_DELAY_SECONDS)
    try:
        async with AsyncSessionLocal() as db:
            done = await cv_qc.recompute_outdated(db)
    except asyncio.CancelledError:
        raise
    except Exception as exc:  # noqa: BLE001 — zadanie tła nie może paść
        logger.warning("cv qc recompute: failed (%s)", type(exc).__name__)
        return
    if done:
        logger.info("cv qc recompute: %d pairs recomputed", done)
