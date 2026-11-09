"""Strona wyboru terminu z maila: publiczne trasy bez logowania.

Reguły: ``docs/claude/rekrutacja-tablica/rekrutacja-wlasna.md``. Bez
``from __future__ import annotations``: slowapi #579.
"""

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import AwareDatetime, BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.rate_limit import client_ip_key, limiter
from app.services.own_hiring import booking as booking_service
from app.services.own_hiring.service import OwnHiringError

READ_LIMIT = "60/minute"
WRITE_LIMIT = "10/minute"

_NOINDEX_HEADERS = {
    "X-Robots-Tag": "noindex",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
}


def _noindex(response: Response) -> None:
    response.headers.update(_NOINDEX_HEADERS)


router = APIRouter(dependencies=[Depends(_noindex)])


class BookIn(BaseModel):
    start: AwareDatetime


class NoFitIn(BaseModel):
    note: Optional[str] = Field(None, max_length=500)


def _http(exc: OwnHiringError) -> HTTPException:
    return HTTPException(
        status_code=exc.status, detail={"code": exc.code, "message": exc.message}
    )


@router.get("/{token}")
@limiter.limit(READ_LIMIT, key_func=client_ip_key)
async def view(
    request: Request, token: str, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await booking_service.public_view(db, token)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/{token}/book")
@limiter.limit(WRITE_LIMIT, key_func=client_ip_key)
async def book(
    request: Request, token: str, body: BookIn, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await booking_service.public_book(db, token, body.start)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/{token}/cancel")
@limiter.limit(WRITE_LIMIT, key_func=client_ip_key)
async def cancel(
    request: Request, token: str, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await booking_service.public_cancel(db, token)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/{token}/no-fit")
@limiter.limit(WRITE_LIMIT, key_func=client_ip_key)
async def no_fit(
    request: Request, token: str, body: NoFitIn, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await booking_service.public_no_fit(db, token, body.note)
    except OwnHiringError as exc:
        raise _http(exc) from exc


@router.post("/{token}/withdraw")
@limiter.limit(WRITE_LIMIT, key_func=client_ip_key)
async def withdraw(
    request: Request, token: str, db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        return await booking_service.public_withdraw(db, token)
    except OwnHiringError as exc:
        raise _http(exc) from exc
