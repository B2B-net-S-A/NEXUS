"""Finanse → dekret i eksport do Symfonii FK (księgowość E2, 0697).

Prefiks ``/api/finance/posting`` (``app/main.py``, za wyłącznikiem programu
„Ludzi w NEXUSIE”). Bramki jak w E1: sekcja Finanse (router), uprawnienie
„Moduł Finanse” (``FinanceModuleUser``) i moduł „Księgowość” (wyłączony = 404,
admin widzi zawsze). Plan kont i reguły zmienia „Moduł Finanse”. Faktury osób
zespołu (D2) widzą tylko Płace i admin — także w dekrecie, eksporcie i paczkach.

* ``GET/POST /accounts``, ``PATCH /accounts/{id}`` — plan kont,
* ``GET/POST /rules``, ``PATCH /rules/{id}`` — reguły dekretu,
  ``GET /counterparty-options?q=`` — kontrahent do reguły,
* ``POST /entries/{id}/recalculate`` — „Przelicz” dekret z reguły,
  ``PUT /entries/{id}/decree`` — ręczna korekta pozycji (Wn = Ma, inaczej 422),
* ``GET /export?month=`` — lista miesiąca per rejestr z kontrolą (M3),
* ``GET /batches?month=``, ``POST /batches`` (paczka + plik),
  ``GET /batches/{id}/file`` (ten sam plik przy każdym pobraniu),
  ``POST /batches/{id}/book`` („Oznacz jako zaksięgowane”),
  ``POST /batches/{id}/cancel`` („Anuluj paczkę”).
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.finance_ledger import MONTH_PATTERN, Category, _open
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.user import User
from app.services.finance_ledger import costs, posting, posting_export, posting_setup
from app.services.finance_ledger.export_formats import DEFAULT_FORMAT, FORMATS
from app.services.finance_posting_schema import (
    ACCOUNT_MAX,
    ACCOUNT_NAME_MAX,
    DOC_TYPE_MAX,
    SERVICE_MAX,
    TEMPLATE_MAX,
)
from app.services.hr.payroll_access import is_payroll

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

AccountKind = Literal["cost", "vat", "settlement", "revenue"]
Deduction = Literal["full", "none"]
Register = Literal["purchase", "sale"]
FileFormat = Literal["neutral_xlsx", "neutral_csv"]


class AccountIn(BaseModel):
    number: str = Field(max_length=ACCOUNT_MAX + 8)
    name: str = Field(max_length=ACCOUNT_NAME_MAX)
    kind: AccountKind


class AccountPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=ACCOUNT_NAME_MAX)
    kind: Optional[AccountKind] = None
    active: Optional[bool] = None


class RuleFields(BaseModel):
    cost_account: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    vat_account: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    deduction: Optional[Deduction] = None
    # „register” zasłania atrybut ``BaseModel`` — w JSON-ie zostaje ta nazwa.
    model_config = ConfigDict(populate_by_name=True)
    register_: Optional[Register] = Field(default=None, alias="register")
    doc_type: Optional[str] = Field(default=None, max_length=DOC_TYPE_MAX + 4)
    service_label: Optional[str] = Field(default=None, max_length=SERVICE_MAX)
    description_template: Optional[str] = Field(default=None, max_length=TEMPLATE_MAX)
    active: Optional[bool] = None


class RuleIn(RuleFields):
    category: Category
    counterparty_id: Optional[int] = None


class PositionIn(BaseModel):
    kind: Literal["cost", "vat", "counterparty"]
    account: str = Field(max_length=ACCOUNT_MAX + 8)
    side: Literal["debit", "credit"]
    amount: Decimal = Field(gt=0, max_digits=14, decimal_places=2)
    vat_rate: Optional[str] = Field(default=None, max_length=8)
    deduction: Optional[Deduction] = None


class DecreeIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    register_: Register = Field(alias="register")
    doc_type: str = Field(max_length=DOC_TYPE_MAX + 4)
    description: str = Field(default="", max_length=posting.DESCRIPTION_MAX)
    positions: list[PositionIn] = Field(min_length=1, max_length=posting.POSITIONS_MAX)


class BatchIn(BaseModel):
    month: str = Field(pattern=MONTH_PATTERN)
    format: FileFormat = DEFAULT_FORMAT


def _fail(exc: costs.LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _month(raw: str) -> date:
    return date(int(raw[:4]), int(raw[5:7]), 1)


# ── Plan kont ────────────────────────────────────────────────────────────────


@router.get("/accounts")
async def list_accounts(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return {"items": await posting_setup.list_accounts(db)}


@router.post("/accounts", status_code=201)
async def create_account(
    body: AccountIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await posting_setup.create_account(
            db, body.model_dump(), actor_id=current_user.id
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    payload = posting_setup.account_payload(row)
    await db.commit()
    return payload


@router.patch("/accounts/{account_id}")
async def update_account(
    account_id: int,
    body: AccountPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await posting_setup.update_account(
            db,
            account_id,
            body.model_dump(exclude_unset=True),
            actor_id=current_user.id,
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    payload = posting_setup.account_payload(row)
    await db.commit()
    return payload


# ── Reguły dekretu ───────────────────────────────────────────────────────────


@router.get("/rules")
async def list_rules(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return {"items": await posting_setup.list_rules(db)}


@router.get("/counterparty-options")
async def counterparty_options(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    q: str = Query("", max_length=120),
) -> dict[str, Any]:
    await _open(db, current_user)
    return {"items": await posting_setup.counterparty_options(db, q)}


@router.post("/rules", status_code=201)
async def create_rule(
    body: RuleIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await posting_setup.create_rule(
            db,
            body.model_dump(exclude_unset=True, by_alias=True),
            actor_id=current_user.id,
        )
        payload = await posting_setup.rule_view(db, row)
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return payload


@router.patch("/rules/{rule_id}")
async def update_rule(
    rule_id: int,
    body: RuleFields,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        row = await posting_setup.update_rule(
            db,
            rule_id,
            body.model_dump(exclude_unset=True, by_alias=True),
            actor_id=current_user.id,
        )
        payload = await posting_setup.rule_view(db, row)
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return payload


# ── Dekret wpisu ─────────────────────────────────────────────────────────────


async def _card(db: AsyncSession, entry_id: int, user: User) -> dict[str, Any]:
    return await costs.card(db, entry_id, viewer_id=user.id, payroll=is_payroll(user))


@router.post("/entries/{entry_id}/recalculate")
async def recalculate_decree(
    entry_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await posting.recalculate(
            db,
            entry_id,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await _card(db, entry_id, current_user)


@router.put("/entries/{entry_id}/decree")
async def set_decree(
    entry_id: int,
    body: DecreeIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await posting.set_manual(
            db,
            entry_id,
            body.model_dump(mode="json", by_alias=True),
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await _card(db, entry_id, current_user)


# ── Eksport miesiąca ─────────────────────────────────────────────────────────


@router.get("/export")
async def export_preview(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    month: str = Query(..., pattern=MONTH_PATTERN),
) -> dict[str, Any]:
    await _open(db, current_user)
    payroll = is_payroll(current_user)
    result = await posting_export.preview(db, _month(month), payroll=payroll)
    result["batches"] = await posting_export.list_batches(
        db, _month(month), payroll=payroll
    )
    return result


@router.get("/batches")
async def list_batches(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    month: Optional[str] = Query(None, pattern=MONTH_PATTERN),
) -> dict[str, Any]:
    await _open(db, current_user)
    return {
        "items": await posting_export.list_batches(
            db, _month(month) if month else None, payroll=is_payroll(current_user)
        )
    }


@router.post("/batches", status_code=201)
async def create_batch(
    body: BatchIn, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        batch, skipped = await posting_export.create_batch(
            db,
            _month(body.month),
            body.format,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
        payload = await posting_export.batch_payload(db, batch)
        payload["skipped"] = skipped
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return payload


@router.get("/batches/{batch_id}/file")
async def batch_file(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> Response:
    await _open(db, current_user)
    try:
        batch = await posting_export.batch_file(
            db, batch_id, payroll=is_payroll(current_user)
        )
    except costs.LedgerError as exc:
        raise _fail(exc) from exc
    fmt = FORMATS.get(batch.file_format)
    return Response(
        content=batch.file_content,
        media_type=fmt.media_type if fmt else "application/octet-stream",
        headers={
            "Content-Disposition": content_disposition(batch.file_name),
            "X-File-SHA256": batch.file_sha256,
            "Access-Control-Expose-Headers": "Content-Disposition, X-File-SHA256",
            "Cache-Control": "no-store",
        },
    )


@router.post("/batches/{batch_id}/book")
async def book_batch(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        batch = await posting_export.book_batch(
            db,
            batch_id,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
        payload = await posting_export.batch_payload(db, batch)
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return payload


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        batch = await posting_export.cancel_batch(
            db,
            batch_id,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
        payload = await posting_export.batch_payload(db, batch)
    except costs.LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return payload
