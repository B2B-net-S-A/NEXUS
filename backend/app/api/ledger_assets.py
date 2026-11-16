"""Księgowość → Środki trwałe i WNiP (K6, 0703): ewidencja, plan, dokumenty, AM.

Prefiks ``/api/accounting`` (jak księga K1, ``app/main.py``). Bramki: sekcja
Finanse (router), „Moduł Finanse” (``FinanceModuleUser``) i przełączniki
modułów ``ledger`` oraz ``assets`` (wyłączony = 404, admin widzi zawsze).
W handlerach: zmiany ewidencji, dokumenty środka i import — lista „Księgowi”
albo admin (403); konta modułu — tylko admin (403). Naliczenie miesiąca
(„Nalicz amortyzację”) robi szkice w buforze jak „Zaksięguj miesiąc” —
„Moduł Finanse”; zatwierdza lista „Księgowi”.

* ``GET /assets?year=&month=&scope=`` — ewidencja z wartościami na koniec
  miesiąca, odpis miesiąca, stan dokumentu AM,
* ``GET /assets/{id}?year=&month=`` — karta: plan bilansowy i podatkowy,
  dokumenty środka i ich zapisy w księdze,
* ``POST /assets``, ``PATCH/DELETE /assets/{id}`` — ewidencja (OT z nowym
  środkiem), ``POST /assets/{id}/operations`` (UL, MT, LT, SP),
  ``DELETE /assets/operations/{id}`` (ostatni dokument środka),
* ``POST /assets/sync`` — dokumenty środków i AM miesiąca do bufora,
* ``POST /assets/import?year=&month=&save=`` — ewidencja z Symfonii ŚT
  ze stanem na koniec miesiąca (podgląd albo zapis),
* ``GET /assets/options/equipment``, ``GET /assets/options/cost-entries`` —
  pozycje „Sprzętu” bez karty środka i faktury z kolejki kosztów,
* ``PUT /assets/settings`` — konta modułu (amortyzacja, przyjęcie, zbycie).
"""

from datetime import date
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.user import User
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.ledger import (
    assets,
    assets_import,
    assets_view,
    documents,
    sources,
    years,
)
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import Viewer
from app.services.ledger_assets_schema import (
    INVENTORY_MAX,
    KST_MAX,
    NAME_MAX,
    NOTE_MAX,
    OPERATION_NOTE_MAX,
)
from app.services.ledger_schema import ACCOUNT_MAX, MPK_MAX

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

Method = Literal["linear", "degressive", "one_off", "none"]
ACCOUNT_FIELD = ACCOUNT_MAX + 8


class OpeningBody(BaseModel):
    month: date
    balance: Decimal = Field(default=Decimal(0), ge=0, max_digits=15, decimal_places=2)
    tax: Optional[Decimal] = Field(default=None, ge=0, max_digits=15, decimal_places=2)
    balance_year: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=15, decimal_places=2
    )
    tax_year: Optional[Decimal] = Field(
        default=None, ge=0, max_digits=15, decimal_places=2
    )


class AssetFields(BaseModel):
    name: Optional[str] = Field(default=None, max_length=NAME_MAX)
    kind: Optional[Literal["fixed", "intangible"]] = None
    kst: Optional[str] = Field(default=None, max_length=KST_MAX)
    inventory_number: Optional[str] = Field(default=None, max_length=INVENTORY_MAX)
    accepted_on: Optional[date] = None
    initial_value: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=15, decimal_places=2
    )
    asset_account: Optional[str] = Field(default=None, max_length=ACCOUNT_FIELD)
    depreciation_account: Optional[str] = Field(default=None, max_length=ACCOUNT_FIELD)
    mpk: Optional[str] = Field(default=None, max_length=MPK_MAX + 4)
    balance_method: Optional[Method] = None
    balance_rate: Optional[Decimal] = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    tax_method: Optional[Method] = None
    tax_rate: Optional[Decimal] = Field(
        default=None, ge=0, le=100, max_digits=5, decimal_places=2
    )
    coefficient: Optional[Decimal] = Field(
        default=None, ge=1, le=2, max_digits=3, decimal_places=2
    )
    equipment_item_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=NOTE_MAX)
    opening: Optional[OpeningBody] = None
    post_intake: Optional[bool] = None
    counter_account: Optional[str] = Field(default=None, max_length=ACCOUNT_FIELD)
    cost_entry_id: Optional[int] = None


class AssetBody(AssetFields):
    name: str = Field(max_length=NAME_MAX)
    accepted_on: date
    initial_value: Decimal = Field(gt=0, max_digits=15, decimal_places=2)
    mpk: str = Field(default="OG", max_length=MPK_MAX + 4)
    balance_method: Method = "linear"
    balance_rate: Decimal = Field(
        default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2
    )
    tax_method: Method = "linear"
    tax_rate: Decimal = Field(
        default=Decimal(0), ge=0, le=100, max_digits=5, decimal_places=2
    )


class OperationBody(BaseModel):
    op_type: Literal["UL", "MT", "LT", "SP"]
    op_date: date
    amount: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=15, decimal_places=2
    )
    mpk_to: Optional[str] = Field(default=None, max_length=MPK_MAX + 4)
    counter_account: Optional[str] = Field(default=None, max_length=ACCOUNT_FIELD)
    cost_entry_id: Optional[int] = None
    note: str = Field(default="", max_length=OPERATION_NOTE_MAX)


class SyncBody(BaseModel):
    year: int = Field(ge=years.YEAR_MIN, le=years.YEAR_MAX)
    month: int = Field(ge=1, le=12)


class AssetsAccountsBody(BaseModel):
    cost_account: str = Field(max_length=ACCOUNT_FIELD)
    intake_account: str = Field(max_length=ACCOUNT_FIELD)
    disposal_account: str = Field(max_length=ACCOUNT_FIELD)


def _fail(exc: LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _grosze(amount: Optional[Decimal]) -> Optional[int]:
    return None if amount is None else int((amount * 100).to_integral_value())


async def _context(
    db: AsyncSession, user: User
) -> tuple[ledger_settings.LedgerSettings, Viewer]:
    current = await ledger_settings.load(db)
    if not (
        ledger_settings.module_open(user, current, "ledger")
        and ledger_settings.module_open(user, current, "assets")
    ):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return current, documents.viewer_for(user, current)


def _require_approver(viewer: Viewer) -> None:
    if not viewer.approver:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "Ewidencję środków zmienia osoba z listy „Księgowi” albo administrator.",
        )


def _values(body: AssetFields, *, partial: bool) -> dict[str, Any]:
    values = body.model_dump(exclude_unset=partial)
    if "initial_value" in values:
        values["initial_value"] = _grosze(body.initial_value)
    if "opening" in values:
        opening = body.opening
        values["opening"] = (
            None
            if opening is None
            else {
                "month": opening.month,
                "balance": _grosze(opening.balance),
                "tax": _grosze(
                    opening.tax if opening.tax is not None else opening.balance
                ),
                "balance_year": _grosze(opening.balance_year),
                "tax_year": _grosze(
                    opening.tax_year
                    if opening.tax_year is not None
                    else opening.balance_year
                ),
            }
        )
    return values


def _month(year: int, month: int) -> date:
    return date(year, month, 1)


# ── Ewidencja ────────────────────────────────────────────────────────────────


@router.get("/assets")
async def list_assets(
    current_user: FinanceModuleUser,
    year: int = Query(ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month: int = Query(ge=1, le=12),
    scope: Literal["month", "all"] = Query("month"),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    return await assets_view.overview(
        db, month=_month(year, month), scope=scope, settings=current, viewer=viewer
    )


@router.get("/assets/options/equipment")
async def equipment_options(
    current_user: FinanceModuleUser,
    q: str = Query("", max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    return {"items": await assets_view.equipment_options(db, q)}


@router.get("/assets/options/cost-entries")
async def cost_entry_options(
    current_user: FinanceModuleUser,
    q: str = Query("", max_length=60),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    return {"items": await assets_view.cost_entry_options(db, q)}


@router.put("/assets/settings")
async def set_assets_accounts(
    body: AssetsAccountsBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    if not viewer.admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "To ustawienie zmienia tylko administrator."
        )
    try:
        current = await ledger_settings.set_assets_accounts(
            db, body.model_dump(), actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)["assets"]


@router.post("/assets/sync")
async def sync_assets(
    body: SyncBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Dokumenty środków (OT, UL, LT, SP) i AM miesiąca do bufora."""

    current, viewer = await _context(db, current_user)
    try:
        operations = await sources.sync_month(
            db,
            sources.ASSET_DOCS,
            body.year,
            body.month,
            viewer=viewer,
            settings=current,
        )
        depreciation = await sources.sync_month(
            db, sources.ASSETS, body.year, body.month, viewer=viewer, settings=current
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"operations": operations, "depreciation": depreciation}


@router.post("/assets/import")
async def import_assets(
    current_user: FinanceModuleUser,
    year: int = Query(ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month: int = Query(ge=1, le=12),
    save: bool = Query(False),
    file: UploadFile = File(
        ..., description="Ewidencja z Symfonii Środki Trwałe (XLSX albo CSV)"
    ),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    _require_approver(viewer)
    content = await file.read(assets_import.MAX_BYTES + 1)
    try:
        result = await assets_import.run(
            db,
            content,
            month=_month(year, month),
            save=save,
            viewer=viewer,
            settings=current,
        )
    except ImportFileError as exc:
        await db.rollback()
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    if save:
        await db.commit()
    else:
        await db.rollback()
    return result


@router.post("/assets", status_code=status.HTTP_201_CREATED)
async def create_asset(
    body: AssetBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        asset = await assets.create_asset(
            db, _values(body, partial=False), viewer=viewer, settings=current
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"id": asset.id, "inventory_number": asset.inventory_number}


@router.delete("/assets/operations/{op_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_operation(
    op_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        await assets.delete_operation(db, op_id, viewer=viewer)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()


@router.get("/assets/{asset_id}")
async def asset_card(
    asset_id: int,
    current_user: FinanceModuleUser,
    year: int = Query(ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month: int = Query(ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        return await assets_view.card(
            db, asset_id, month=_month(year, month), viewer=viewer
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.patch("/assets/{asset_id}")
async def update_asset(
    asset_id: int,
    body: AssetFields,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        asset = await assets.update_asset(
            db,
            asset_id,
            _values(body, partial=True),
            viewer=viewer,
            settings=current,
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"id": asset.id, "inventory_number": asset.inventory_number}


@router.delete("/assets/{asset_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_asset(
    asset_id: int,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> None:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        await assets.delete_asset(db, asset_id, viewer=viewer)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()


@router.post("/assets/{asset_id}/operations", status_code=status.HTTP_201_CREATED)
async def add_operation(
    asset_id: int,
    body: OperationBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    current, viewer = await _context(db, current_user)
    _require_approver(viewer)
    values = body.model_dump()
    values["amount"] = _grosze(body.amount)
    try:
        op = await assets.add_operation(
            db, asset_id, values, viewer=viewer, settings=current
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"id": op.id, "number": op.number}
