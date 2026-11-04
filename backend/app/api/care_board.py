"""Opieka · „Do zrobienia” (kanban) i „Klienci” (przebudowa opieki, 22.10.2026).

Trasy pod ``/api/care`` — router dołącza ``app/api/contract_care.py`` (ten sam
prefiks i wyłącznik programu ``_HR_PROGRAM`` z ``app/main.py``). Bramki
z ``app/api/care_gates.py``:

* ``GET /board`` i ``GET /clients`` — czytelnicy opieki (``CareReader``;
  zakres DL = portfel). Karty opinii menedżerów i zdrowie relacji tylko
  w kręgu D11; karty popytu tylko DL klienta i admin.
* ``PUT /board/state`` — piszący opiekę (``CareWriter``); prawo do karty
  sprawdza serwis: kontrakt w zakresie (rozmowa, decyzja), krąg D11 (opinia),
  DL klienta albo admin (popyt).

Odczyt niczego nie zapisuje.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import CareReader, CareWriter
from app.core.database import get_db
from app.core.scheduling import business_today, local_now
from app.models.user import User
from app.services.care import board as care_board
from app.services.care import portfolio as care_portfolio
from app.services.care_board_schema import BOARD_NOTE_MAX, KEY_MAX

router = APIRouter()


@router.get("/board")
async def board(
    scope: Literal["mine", "all"] = "mine",
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Karty opieki na tablicę „Do zrobienia” i „Zrobione” z tego tygodnia."""

    return await care_board.board(
        db, user=current_user, scope=scope, today=business_today()
    )


class BoardStateBody(BaseModel):
    key: str = Field(min_length=3, max_length=KEY_MAX)
    column: Literal["new", "in_progress", "waiting"]
    scheduled_at: Optional[datetime] = None
    retry_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=BOARD_NOTE_MAX)


@router.put("/board/state")
async def set_board_state(
    body: BoardStateBody,
    current_user: User = Depends(CareWriter),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Przeniesienie karty opieki: „Nowa” kasuje stan, „W toku”/„Czeka” go zapisują."""

    return await care_board.set_state(
        db,
        user=current_user,
        raw_key=body.key,
        column=body.column,
        scheduled_at=body.scheduled_at,
        retry_on=body.retry_on,
        note=body.note,
        today=business_today(),
        now=local_now(),
    )


@router.get("/clients")
async def clients(
    scope: Literal["mine", "all"] = "mine",
    current_user: User = Depends(CareReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """„Klienci” w Opiece: kompletność wiedzy, zdrowie, popyt, kończący w 60 dni."""

    return await care_portfolio.clients(
        db, current_user, scope=scope, today=business_today()
    )
