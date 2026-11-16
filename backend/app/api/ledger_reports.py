"""Księgowość → Sprawozdania (K8a): bilans, RZiS i pozycje kont.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``reports`` (wyłączony = 404, admin widzi zawsze).
Pozycję konta zmienia się zapisem konta w planie (``PATCH /chart/{id}``,
pole ``report_line`` — walidacja znacznikiem MF).

* ``GET /reports/statements?year=&month_from=&month_to=`` — bilans na koniec
  ``month_to`` i RZiS (wariant porównawczy) za ``month_from``–``month_to``,
  konta bez pozycji i ostrzeżenia,
* ``GET /reports/accounts`` — plan kont z pozycją sprawozdania i jej źródłem,
* ``GET /reports/markers`` — słownik znaczników MF (JPK_KR_PD, jednostki
  pozostałe) do wyboru pozycji.
"""

from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import markers, statements
from app.services.ledger import settings as ledger_settings

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


async def _require_open(db: AsyncSession, user: User) -> None:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "reports")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )


@router.get("/reports/statements")
async def financial_statements(
    current_user: FinanceModuleUser,
    year: int = Query(ge=2000, le=2100),
    month_from: Optional[int] = Query(default=None, ge=1, le=12),
    month_to: Optional[int] = Query(default=None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    try:
        return await statements.statements(
            db, year=year, month_from=month_from, month_to=month_to
        )
    except LedgerError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/reports/accounts")
async def report_accounts(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    return {"items": await statements.account_positions(db)}


@router.get("/reports/markers")
async def report_markers(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _require_open(db, current_user)
    return {"items": markers.catalogue()}
