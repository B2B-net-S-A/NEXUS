"""Opieka · ATLAS — sygnały sprzedażowe z kart technologii („klient zatrudnia”).

Prefiks ``/api/care`` (wpięty w ``app/main.py`` obok ``contract_care``).
Odczyt: klucz konta serwisowego z ``sales_signals:read`` albo admin z JWT
(``AtlasReader``); zwrot statusów: ``sales_signals:write`` albo admin
(``AtlasAdmin``). Bramki: ``app/api/care_gates.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import AtlasAdmin, AtlasReader
from app.api.deps import Caller
from app.core.database import get_db
from app.services.care import signals
from app.services.contract_care_schema import SHORT_TEXT_MAX

router = APIRouter()


@router.get("/atlas/sales-signals")
async def atlas_sales_signals(
    since: Optional[str] = Query(default=None, max_length=64),
    caller: Caller = Depends(AtlasReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Karty „klient zatrudnia” z wynikiem obsługi po stronie ATLASA.

    Pusta lista to poprawna odpowiedź (``count`` = 0) — ATLAS rozróżnia ją od
    awarii po kodzie HTTP. ``since`` (ISO-8601 ze strefą) zawęża do kart
    zmienionych od tej chwili; zła data = 422, nie cichy pełny eksport.
    """

    parsed: Optional[datetime] = None
    if since:
        try:
            parsed = datetime.fromisoformat(since.replace("Z", "+00:00"))
        except ValueError as exc:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "since musi być datą ISO-8601 ze strefą (np. 2026-09-01T10:00:00Z).",
            ) from exc
        if parsed.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "since musi mieć strefę czasową (np. 2026-09-01T10:00:00Z).",
            )
    rows = await signals.export(db, since=parsed)
    return {"count": len(rows), "signals": rows}


class SignalStatusItem(BaseModel):
    signal_id: str = Field(min_length=1, max_length=100)
    status: Literal["converted", "archived"]
    handled_at: datetime
    deal_title: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)
    handled_by_name: Optional[str] = Field(default=None, max_length=200)
    reason: Optional[str] = Field(default=None, max_length=2000)


class SignalStatusBody(BaseModel):
    updates: list[SignalStatusItem] = Field(max_length=200)


@router.post("/atlas/sales-signals/status")
async def atlas_sales_signal_status(
    body: SignalStatusBody,
    _caller: Caller = Depends(AtlasAdmin),
    db: AsyncSession = Depends(get_db),
) -> dict:
    for item in body.updates:
        if item.handled_at.tzinfo is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "handled_at musi mieć strefę czasową.",
            )
    result = await signals.apply_statuses(
        db,
        [signals.StatusUpdate(**item.model_dump()) for item in body.updates],
    )
    return result
