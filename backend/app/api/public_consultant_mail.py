"""Publiczny wypis konsultanta z komunikatów informacyjnych (O12).

Prefiks ``/api/public/consultant-mail`` (wpina koordynator w ``app/main.py``),
strona ``/wypis/{token}`` we froncie. Trasy mają ``@limiter.limit`` — dlatego
moduł NIE ma ``from __future__ import annotations`` (ciało żądania lądowałoby
jako parametr query → 422).

Token z maila porównujemy z SHA-256 w bazie. Zły, nieznany i zbyt długi token
dają to samo 404 z tym samym zdaniem; odpowiedź nie niesie danych osobowych
(ani imienia, ani adresu, ani klienta). GET tylko mówi, czy wypis już jest —
skanery linków w poczcie otwierają adresy same, więc wypis to POST.
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import limiter
from app.services.care import announcements

router = APIRouter()

GENERIC_404 = "Link nieprawidłowy lub wygasły."

# Limit per adres (czyli per token) i wspólny kubełek per IP na wszystkie
# tokeny — seria różnych adresów nie posłuży do zgadywania.
SHARED_READ = "60/minute"
SHARED_WRITE = "10/minute"


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail=GENERIC_404)


@router.get("/unsubscribe/{token}")
@limiter.limit("30/minute")
@limiter.shared_limit(SHARED_READ, scope="consultant-mail-read")
async def unsubscribe_state(
    token: str,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    state = await announcements.unsubscribe_state(db, token)
    if state is None:
        raise _not_found()
    return {"unsubscribed": state}


@router.post("/unsubscribe/{token}")
@limiter.limit("5/minute;30/hour")
@limiter.shared_limit(SHARED_WRITE, scope="consultant-mail-write")
async def unsubscribe(
    token: str,
    request: Request,  # wymagane przez limiter slowapi
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not await announcements.unsubscribe(db, token):
        raise _not_found()
    return {"unsubscribed": True}
