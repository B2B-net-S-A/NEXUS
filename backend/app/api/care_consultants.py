"""Opieka · „Konsultanci”, rytm kontaktu i „Przydział” (etap 3, O7–O10, 17.10.2026).

Trasy pod ``/api/care`` — router dołącza ``app/api/contract_care.py`` (ten
sam prefiks, bez osobnego wpisu w ``app/main.py``). Bramki z
``app/api/care_gates.py``:

* odczyt listy, rytmu i przydziału — czytelnicy opieki i head back office
  (``RhythmReader``; zakres DL = portfel, head back office — wszyscy klienci,
  także bez sekcji Delivery: O8, O10). Opinia menedżera w sygnałach tylko
  dla ról z D11,
* zmiana rytmu — ta sama bramka, a prawo do kontraktu (opiekun kontraktu, DL
  klienta, head back office, admin) sprawdza ``care/cadence.set_cadence``,
* zmiana opiekuna wielu kontraktów i próg obciążenia — ``CareAssigner``
  (head back office, admin).
"""

from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.care_gates import CareAssigner, RhythmReader, reads_client_people
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.care import access as care_access
from app.services.care import assignment as care_assignment
from app.services.care import cadence as care_cadence
from app.services.care import consultants as care_consultants
from app.services.care.assignment import MAX_BULK, THRESHOLD_MAX, OwnerReason
from app.services.contract_care_schema import SHORT_TEXT_MAX

router = APIRouter()

Level = Literal["biweekly", "monthly", "quarterly", "milestones", "paused"]
#: Powody zmiany rytmu z okna (``imported`` ustawia tylko import z Compassa).
CadenceReason = Literal[
    "new_at_client",
    "weak_feedback",
    "order_end",
    "wants_change",
    "stable",
    "person_request",
    "long_absence",
    "other",
]


@router.get("/consultants")
async def consultants(
    current_user: User = Depends(RhythmReader), db: AsyncSession = Depends(get_db)
) -> dict:
    """„Konsultanci”: rytm, następna i ostatnia rozmowa, sygnały, rozmowy w miesiącu."""

    return await care_consultants.consultants(
        db,
        current_user,
        today=business_today(),
        include_feedback=reads_client_people(current_user),
    )


@router.get("/contracts/{contract_id}/cadence")
async def contract_cadence(
    contract_id: int,
    level: Optional[Level] = Query(default=None),
    until_on: Optional[date] = Query(default=None),
    current_user: User = Depends(RhythmReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Okno „Rytm kontaktu”; ``level`` (i ``until_on``) = podgląd zmiany bez zapisu."""

    contract = await care_access.load_contract(
        db, contract_id, current_user, rhythm=True
    )
    return await care_cadence.cadence_payload(
        db,
        contract,
        user=current_user,
        today=business_today(),
        include_feedback=reads_client_people(current_user),
        proposal=care_cadence.Proposal(level, until_on) if level else None,
    )


class CadenceBody(BaseModel):
    level: Level
    reason: CadenceReason
    note: Optional[str] = Field(default=None, max_length=SHORT_TEXT_MAX)
    until_on: Optional[date] = None


@router.post("/contracts/{contract_id}/cadence", status_code=status.HTTP_201_CREATED)
async def set_contract_cadence(
    contract_id: int,
    body: CadenceBody,
    current_user: User = Depends(RhythmReader),
    db: AsyncSession = Depends(get_db),
) -> dict:
    contract = await care_access.load_contract(
        db, contract_id, current_user, rhythm=True
    )
    today = business_today()
    await care_cadence.set_cadence(
        db,
        contract,
        user=current_user,
        level=body.level,
        reason=body.reason,
        note=body.note,
        until_on=body.until_on,
        today=today,
    )
    return await care_cadence.cadence_payload(
        db,
        contract,
        user=current_user,
        today=today,
        include_feedback=reads_client_people(current_user),
    )


@router.get("/assignment")
async def assignment(
    current_user: User = Depends(RhythmReader), db: AsyncSession = Depends(get_db)
) -> dict:
    """„Przydział”: opiekunowie z obciążeniem z rytmów, kontrakty z podpowiedzią."""

    return await care_assignment.overview(db, current_user, today=business_today())


class AssignBody(BaseModel):
    contract_ids: list[int] = Field(min_length=1, max_length=MAX_BULK)
    owner_user_id: int
    reason: OwnerReason


@router.post("/assignment")
async def assign_owner(
    body: AssignBody,
    current_user: User = Depends(CareAssigner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    return await care_assignment.assign(
        db,
        actor=current_user,
        contract_ids=body.contract_ids,
        owner_id=body.owner_user_id,
        reason=body.reason,
        today=business_today(),
    )


class ThresholdBody(BaseModel):
    monthly_conversations: Optional[int] = Field(default=None, ge=1, le=THRESHOLD_MAX)


@router.put("/assignment/threshold")
async def set_load_threshold(
    body: ThresholdBody,
    current_user: User = Depends(CareAssigner),
    db: AsyncSession = Depends(get_db),
) -> dict:
    value = await care_assignment.save_threshold(
        db, value=body.monthly_conversations, actor=current_user
    )
    return {"monthly_conversations": value}
