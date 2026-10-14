"""Wpis o pobraniu pliku CV (decyzja Artura 12.10.2026, D5).

Mierzymy, jak często CV wychodzi z NEXUSA do Worda. Podgląd i pobranie idą
tą samą trasą, więc przycisk „Pobierz” dokleja ``intent=download`` i miejsce
w aplikacji (``frontend/src/lib/cv-download-intent.ts``) — bez intencji wpis
nie powstaje. W szczegółach są wyłącznie format, stan, miejsce i numer wersji:
repo i logi są publiczne, a nazwa pliku niesie nazwisko.

Zapis nie może zatrzymać pobrania: idzie w SAVEPOINT-cie, a błąd kończy się
ostrzeżeniem w logu.
"""

from __future__ import annotations

import logging
from typing import Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.activity import Activity

logger = logging.getLogger(__name__)

ACTION = "cv_file_downloaded"
# Lustro `CvDownloadSurface` z frontendu; wszystko inne zapisujemy jako „other”.
SURFACES = frozenset({"editor", "card", "dock", "preview", "cpro", "result", "files"})


async def log_cv_download(
    db: AsyncSession,
    *,
    intent: Optional[str],
    surface: Optional[str],
    entity_type: str,
    entity_id: int,
    user,
    file_format: str,
    state: str,
    version: Optional[int] = None,
) -> None:
    """Dopisz wpis ``cv_file_downloaded``, gdy żądanie było pobraniem pliku.

    Wołaj tuż przed oddaniem pliku — po bramkach dostępu i zgody, żeby
    odmowa nie liczyła się jako pobranie. Commit robi sesja żądania.
    """
    if intent != "download":
        return
    try:
        async with db.begin_nested():
            db.add(
                Activity(
                    entity_type=entity_type,
                    entity_id=entity_id,
                    action=ACTION,
                    user_id=user.id,
                    details={
                        "format": file_format,
                        "state": state,
                        "surface": surface if surface in SURFACES else "other",
                        "version": version,
                    },
                )
            )
    except Exception:  # noqa: BLE001 — pomiar nie może zatrzymać pobrania
        logger.warning(
            "[cv_download] nie zapisano wpisu %s dla %s:%s",
            ACTION,
            entity_type,
            entity_id,
            exc_info=True,
        )
