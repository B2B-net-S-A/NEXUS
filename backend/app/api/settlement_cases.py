"""Finanse → Rozliczenia: karta sprawy („Co dalej”) i lista spraw (25.11.2026).

Moduł Finanse (``FinanceModuleUser``) i sekcja Finanse, jak reszta rozliczeń;
wyłączony moduł ``client_settlements`` = 404 (admin widzi zawsze). Posiadacz
modułu widzi kwoty, ale powody i maile spraw ich nie niosą (konsultant dostaje
tylko MD i godziny, Delivery Lead to, co karta DL). Reguły:
``services/client_settlements/cases.py``.

Nic nie wychodzi samo (decyzja Artura z 25.11.2026): ``POST …/send`` wysyła
przygotowany mail dopiero po kliknięciu „Wyślij”, a treść i adresat liczą się
na serwerze od nowa; ``POST …/call`` zapisuje wynik telefonu. Ustawienia
informacji zwrotnej (``dry_run``, ``external``) tych tras nie dotyczą: to
wysyłka człowieka, nie automatu.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.client_settlements import cases
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.service import SettlementError

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^(20[0-9]{2}|2100)-(0[1-9]|1[0-2])$"
ACTOR_PATTERN = r"^(consultant|client|dl|finance)$"
RESULT_PATTERN = r"^(reached|no_answer|wrong_number)$"


class SendIn(BaseModel):
    actor: str = Field(pattern=ACTOR_PATTERN)
    #: ``True`` = mail eskalacji do opiekuna (DL/KAM), nie do osoby, która działa.
    escalation: bool = False


class CallIn(BaseModel):
    actor: str = Field(pattern=ACTOR_PATTERN)
    result: str = Field(pattern=RESULT_PATTERN)
    note: Optional[str] = Field(None, max_length=cases.NOTE_MAX)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


@router.get("")
async def month_cases(
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    client_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Lista spraw miesiąca: kto działa, bieżący krok, zaległość, klient."""

    await _open(db, current_user)
    return await cases.month_list(db, month, business_today(), client_id=client_id)


@router.get("/contract/{contract_id}")
async def contract_cases(
    contract_id: int,
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Co dalej” na karcie rozliczenia: wszystkie sprawy kontraktu w miesiącu."""

    await _open(db, current_user)
    found = await cases.cases_for_contract(db, contract_id, month, business_today())
    return {"cases": [case.as_dict() for case in found]}


@router.post("/{settlement_id}/send")
async def send(
    settlement_id: int,
    body: SendIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Wyślij”: przygotowany mail po kliknięciu i potwierdzeniu w oknie."""

    await _open(db, current_user)
    today = business_today()
    try:
        outcome, case = await cases.send_mail(
            db,
            settlement_id,
            body.actor,
            escalation=body.escalation,
            by=current_user,
            today=today,
        )
    except SettlementError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    # Ślad zostaje także przy nieudanej wysyłce: wiadomo, kto i kiedy próbował.
    await db.commit()
    if outcome not in cases.SENT_OUTCOMES:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Skrzynka nie przyjęła maila. Spróbuj za chwilę albo wyślij z Outlooka.",
        )
    fresh = await cases.cases_for_contract(db, case.contract_id, case.month, today)
    return {"outcome": outcome, "cases": [c.as_dict() for c in fresh]}


@router.post("/{settlement_id}/call")
async def call(
    settlement_id: int,
    body: CallIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """„Zadzwoniłem”: wynik rozmowy (i notatka) w śladzie sprawy."""

    await _open(db, current_user)
    today = business_today()
    try:
        case = await cases.log_call(
            db,
            settlement_id,
            body.actor,
            result=body.result,
            note=body.note,
            by=current_user,
            today=today,
        )
    except SettlementError as exc:
        await db.rollback()
        raise HTTPException(exc.status, exc.message) from exc
    await db.commit()
    fresh = await cases.cases_for_contract(db, case.contract_id, case.month, today)
    return {"cases": [c.as_dict() for c in fresh]}
