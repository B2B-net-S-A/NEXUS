"""Odtwarzanie pliku szkolenia z biletem (``services/trainings/media.py``).

Prefiks ``/api/public/training-media`` (wpięty za ``_HR_PROGRAM``). Bez logowania:
dostęp daje wyłącznie podpisany bilet jednego pliku, wydany przez trasę z sesją
(pracownik w ``/api/trainings``, konsultant w panelu). Moduł ma ``@limiter.limit``,
więc nie ma ``from __future__ import annotations``.
"""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.models.training import TrainingFile
from app.services.trainings import media, storage
from app.services.trainings.errors import TrainingError

router = APIRouter()

EXPIRED = "Link do odtwarzania wygasł. Odśwież stronę szkolenia."


@router.get("/{file_id}")
@limiter.limit("600/minute")
async def play(
    file_id: int,
    request: Request,
    t: str = "",
    db: AsyncSession = Depends(get_db),
) -> Response:
    if not media.valid(file_id, t, now=media.utcnow()):
        raise HTTPException(status.HTTP_403_FORBIDDEN, EXPIRED)
    item = await db.get(TrainingFile, file_id)
    if item is None or item.status == "replaced":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Nie ma takiego pliku.")
    try:
        return await storage.stream(
            item, range_header=request.headers.get("range"), download=False
        )
    except TrainingError as exc:
        raise HTTPException(
            exc.status, {"message": exc.message, "code": exc.code}
        ) from exc
