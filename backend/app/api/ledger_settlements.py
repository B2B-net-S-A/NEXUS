"""Księgowość → Rozrachunki (K4b, 0706): pozycje kontrahentów i ich rozliczenia.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``bank`` — rozrachunki są częścią etapu K4 „Bank”
(wyłączony = 404, admin widzi zawsze). Rozliczać, cofać i uruchamiać automat
może lista „Księgowi” albo administrator (403); dokumenty płacowe (D2) — tylko
z Płacami.

* ``GET /settlements?as_of=&side=&overdue=&q=`` — kontrahenci z otwartymi
  pozycjami na dzień, wiekowanie należności i zobowiązań, podgląd automatu,
* ``GET /settlements/accounts/{account}?as_of=`` — pozycje konta kontrahenta
  (otwarte i rozliczone) z rozliczeniami,
* ``POST /settlements`` — rozliczenie zaznaczonych pozycji (od najstarszych
  albo na wpisaną kwotę),
* ``POST /settlements/auto?account=`` — automat: wyciąg ↔ faktura, korekta ↔
  faktura, saldo zerowe (wszystkie konta albo jedno),
* ``DELETE /settlements/{id}`` — cofnięcie rozliczenia (ślad zostaje).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import documents, settlements, settlements_view
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import Viewer
from app.services.ledger_schema import ACCOUNT_MAX

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

Side = Literal["all", "receivable", "payable"]
ACCOUNT_PATTERN = r"^[0-9A-Za-z][0-9A-Za-z-]*$"
#: Identyfikatory ponad BIGINT → 422 (inaczej błąd bazy i 500; przegląd K4b).
ID_MAX = 2**63 - 1
LineId = Annotated[int, Field(ge=1, le=ID_MAX)]


class SettleBody(BaseModel):
    debit_ids: list[LineId] = Field(min_length=1, max_length=settlements.SELECT_MAX)
    credit_ids: list[LineId] = Field(min_length=1, max_length=settlements.SELECT_MAX)
    #: Kwota w złotych — tylko przy jednej pozycji Wn i jednej Ma.
    amount: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=15, decimal_places=2
    )


def _fail(exc: LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


async def _context(db: AsyncSession, user: User) -> Viewer:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "bank")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return documents.viewer_for(user, current)


@router.get("/settlements")
async def settlements_overview(
    current_user: FinanceModuleUser,
    as_of: Optional[date] = Query(default=None),
    side: Side = Query(default="all"),
    overdue: bool = Query(default=False),
    q: Optional[str] = Query(default=None, max_length=settlements_view.SEARCH_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await _context(db, current_user)
    return await settlements_view.overview(
        db,
        viewer,
        as_of=as_of or business_today(),
        side=side,
        overdue_only=overdue,
        needle=q,
    )


@router.get("/settlements/accounts/{account}")
async def settlements_account(
    current_user: FinanceModuleUser,
    account: str = Path(max_length=ACCOUNT_MAX, pattern=ACCOUNT_PATTERN),
    as_of: Optional[date] = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await _context(db, current_user)
    try:
        return await settlements_view.account_detail(
            db, viewer, account, as_of=as_of or business_today()
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.post("/settlements", status_code=201)
async def settle_items(
    body: SettleBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await _context(db, current_user)
    amount = (
        int((body.amount * 100).to_integral_value())
        if body.amount is not None
        else None
    )
    try:
        result = await settlements.settle(
            db,
            viewer,
            debit_ids=body.debit_ids,
            credit_ids=body.credit_ids,
            amount=amount,
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.post("/settlements/auto")
async def settle_automatically(
    current_user: FinanceModuleUser,
    account: Optional[str] = Query(
        default=None, max_length=ACCOUNT_MAX, pattern=ACCOUNT_PATTERN
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = await _context(db, current_user)
    try:
        result = await settlements.settle_auto(db, viewer, account=account)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.delete("/settlements/{settlement_id}", status_code=204)
async def remove_settlement(
    current_user: FinanceModuleUser,
    settlement_id: int = Path(ge=1, le=ID_MAX),
    db: AsyncSession = Depends(get_db),
) -> None:
    viewer = await _context(db, current_user)
    try:
        await settlements.unsettle(
            db, viewer, settlement_id, now=datetime.now(timezone.utc)
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
