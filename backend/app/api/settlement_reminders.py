"""Finanse → Rozliczenia: przypomnienia o brakującym raporcie godzin (RCP).

Moduł Finanse (``FinanceModuleUser``) i sekcja Finanse, jak reszta rozliczeń;
wyłączony moduł ``client_settlements`` = 404 (admin widzi zawsze). Przełącznik
automatu i przycisku zapisuje tylko admin (karta „Start rozliczeń”), bo to
wysyłka do ludzi spoza firmy. Reguły: ``services/client_settlements/reminders.py``.

``GET`` niesie dane, których używa też widok „Przebieg miesiąca”: per klient
liczba brakujących, adresat każdego kontraktu i data ostatniego przypomnienia.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.client_settlements import reminders
from app.services.client_settlements import settings as module_settings
from app.services.client_settlements.service import SettlementError
from app.services.hr import audit

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

MONTH_PATTERN = r"^[0-9]{4}-(0[1-9]|1[0-2])$"


class SwitchIn(BaseModel):
    enabled: bool


class SendIn(BaseModel):
    client_id: int = Field(ge=1)
    month: str = Field(pattern=MONTH_PATTERN)


async def _open(db: AsyncSession, user: User) -> None:
    enabled = await module_settings.is_enabled(db)
    if not module_settings.open_for(user, enabled):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, module_settings.MODULE_DISABLED_DETAIL
        )


@router.get("/settings")
async def switch_state(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return {"enabled": await reminders.is_enabled(db)}


@router.put("/settings")
async def set_switch(
    body: SwitchIn, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """Włącznik automatu i przycisku (admin). Domyślnie wyłączony."""

    value = await reminders.set_enabled(db, body.enabled, actor=current_user)
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="client_settlements",
        entity_id=0,
        action="report_reminders_switch_changed",
        details={"enabled": value["enabled"]},
    )
    await db.commit()
    return value


@router.get("")
async def overview(
    current_user: FinanceModuleUser,
    month: str = Query(..., pattern=MONTH_PATTERN),
    client_id: Optional[int] = Query(None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Brakujące raporty miesiąca z adresatami i treścią maila (podgląd)."""

    await _open(db, current_user)
    return await reminders.overview(db, month, client_id=client_id)


@router.post("/send")
async def send(
    body: SendIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    """„Przypomnij (n)” w miesiącu klienta: wysyła od razu, bez powtórek dnia."""

    await _open(db, current_user)
    try:
        counts = await reminders.send_manual(
            db,
            body.client_id,
            body.month,
            actor=current_user,
            today=business_today(),
        )
    except SettlementError as exc:
        raise HTTPException(exc.status, exc.message) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="client_settlements",
        entity_id=body.client_id,
        action="report_reminders_sent",
        details={"month": body.month, **counts},
    )
    await db.commit()
    return counts
