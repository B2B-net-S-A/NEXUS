"""Księgowość → VAT (K5a): rejestry sprzedaży i zakupu z dokumentów księgi.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``vat`` (wyłączony = 404, admin widzi zawsze).
Faktury osób zespołu (D2) widzi tylko osoba z Płacami. Konta modułu zmienia
tylko administrator (403).

* ``GET /vat?year=&month=`` — rejestry miesiąca, sumy grup (pola JPK_V7M),
  lista „do sprawdzenia”,
* ``PUT /vat/settings`` — konto VAT naliczonego.
"""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import documents, vat
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import Viewer
from app.services.ledger_schema import ACCOUNT_MAX

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


class VatAccountsBody(BaseModel):
    input_account: str = Field(max_length=ACCOUNT_MAX + 8)


def _fail(exc: LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _context(
    db: AsyncSession, user: User
) -> tuple[ledger_settings.LedgerSettings, Viewer]:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "vat")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return current, documents.viewer_for(user, current)


@router.get("/vat")
async def vat_registers(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    try:
        return await vat.registers(db, viewer, current, year=year, month=month)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.put("/vat/settings")
async def set_vat_accounts(
    body: VatAccountsBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To ustawienie zmienia tylko administrator."
        )
    try:
        current = await ledger_settings.set_vat_accounts(
            db, body.model_dump(), actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)["vat"]
