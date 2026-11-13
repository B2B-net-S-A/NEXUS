"""Księgowość → księga NEXUSA (K1, 0699): dokumenty, dziennik, obroty, plan kont.

Prefiks ``/api/accounting`` (``app/main.py``, za wyłącznikiem programu „Ludzi
w NEXUSIE” jak reszta Finansów). Bramki: sekcja Finanse (router), uprawnienie
„Moduł Finanse” (``FinanceModuleUser``) i przełącznik modułu ``ledger``
(wyłączony = 404, admin widzi zawsze). W handlerach: zatwierdzenie, storno,
założenie roku i zamknięcie okresu — lista „Księgowi” albo admin (403);
przełączniki, lista „Księgowi”, tryb roku i ponowne otwarcie okresu — tylko
admin (403). Dokumenty płacowe (D2) — tylko Płace i admin (404 dla reszty).

* ``GET /config`` — moduły, rola osoby, lata z okresami,
  ``PUT /config/modules`` i ``PUT /config/accountants`` (admin),
  ``GET /config/candidates`` (admin: konta z „Modułem Finanse”),
* ``POST /years``, ``PATCH /years/{id}`` (tryb), ``POST /periods/{id}/close``,
  ``POST /periods/{id}/reopen``,
* ``GET/POST /documents``, ``GET/PATCH/DELETE /documents/{id}``,
  ``POST /documents/approve``, ``POST /documents/{id}/reverse``,
* ``GET /trial-balance``, ``GET /accounts/card``,
* ``GET/POST /chart``, ``PATCH /chart/{id}``.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.ledger import LedgerYear
from app.models.user import User
from app.services.action_permissions import ProductAction, has_permission
from app.services.effective_access import resolve_effective_access
from app.services.finance_ledger.costs import LedgerError
from app.services.finance_ledger.posting import clean_account
from app.services.ledger import chart, documents, engine, reports, years
from app.services.ledger import settings as ledger_settings
from app.services.ledger.documents import DocumentSpec, Viewer
from app.services.ledger_schema import (
    ACCOUNT_DICTIONARIES,
    ACCOUNT_KINDS,
    ACCOUNT_MAX,
    ACCOUNT_TYPES,
    DESCRIPTION_MAX,
    LINE_TEXT_MAX,
    LINES_MAX,
    MPK_MAX,
    NUMBER_MAX,
    REASON_MAX,
    REPORT_LINE_MAX,
    YEAR_MODES,
)

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)

AMOUNT_MAX = Decimal("1000000000000")
ADMIN_ONLY = "To ustawienie zmienia tylko administrator."


class LineBody(BaseModel):
    side: Literal["debit", "credit"]
    account: str = Field(max_length=ACCOUNT_MAX + 8)
    amount: Decimal = Field(max_digits=15, decimal_places=2)
    description: str = Field(default="", max_length=LINE_TEXT_MAX)
    counterparty_id: Optional[int] = None
    mpk: Optional[str] = Field(default=None, max_length=MPK_MAX + 4)


class DocumentBody(BaseModel):
    doc_type: Literal["PK", "BO"] = "PK"
    number: Optional[str] = Field(default=None, max_length=NUMBER_MAX)
    op_date: date
    doc_date: Optional[date] = None
    description: str = Field(default="", max_length=DESCRIPTION_MAX)
    counterparty_id: Optional[int] = None
    lines: list[LineBody] = Field(min_length=2, max_length=LINES_MAX)


class ApproveBody(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=200)


class ReverseBody(BaseModel):
    op_date: Optional[date] = None
    reason: str = Field(min_length=3, max_length=REASON_MAX)


class ModuleBody(BaseModel):
    module: str = Field(max_length=32)
    enabled: bool


class AccountantsBody(BaseModel):
    user_ids: list[int] = Field(max_length=ledger_settings.ACCOUNTANTS_MAX)


class YearBody(BaseModel):
    year: int = Field(ge=years.YEAR_MIN, le=years.YEAR_MAX)
    mode: Literal["symfonia", "parallel", "nexus"] = "symfonia"


class YearPatch(BaseModel):
    mode: Literal["symfonia", "parallel", "nexus"]


class ReopenBody(BaseModel):
    reason: str = Field(min_length=3, max_length=REASON_MAX)


class AccountBody(BaseModel):
    number: str = Field(max_length=ACCOUNT_MAX + 8)
    name: str = Field(max_length=255)
    kind: Optional[str] = Field(default=None, max_length=12)
    account_type: Optional[str] = Field(default=None, max_length=12)
    parent_number: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    dictionary: Optional[str] = Field(default=None, max_length=16)
    report_line: Optional[str] = Field(default=None, max_length=REPORT_LINE_MAX)


class AccountPatch(BaseModel):
    name: Optional[str] = Field(default=None, max_length=255)
    kind: Optional[str] = Field(default=None, max_length=12)
    account_type: Optional[str] = Field(default=None, max_length=12)
    parent_number: Optional[str] = Field(default=None, max_length=ACCOUNT_MAX + 8)
    dictionary: Optional[str] = Field(default=None, max_length=16)
    report_line: Optional[str] = Field(default=None, max_length=REPORT_LINE_MAX)
    active: Optional[bool] = None


def _fail(exc: LedgerError) -> HTTPException:
    return HTTPException(exc.status, exc.message)


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _context(
    db: AsyncSession, user: User
) -> tuple[ledger_settings.LedgerSettings, Viewer]:
    current = await ledger_settings.load(db)
    if not ledger_settings.module_open(user, current, "ledger"):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, ledger_settings.MODULE_DISABLED_DETAIL
        )
    return current, documents.viewer_for(user, current)


def _require_admin(user: User) -> None:
    if not ledger_settings.is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, ADMIN_ONLY)


def _require_approver(viewer: Viewer) -> None:
    if not viewer.approver:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "To robi osoba z listy „Księgowi” albo administrator.",
        )


def _grosze(amount: Decimal, index: int) -> int:
    if amount == 0:
        raise LedgerError(f"Pozycja {index}: kwota nie może być zerem.", status=422)
    if abs(amount) >= AMOUNT_MAX:
        raise LedgerError(f"Pozycja {index}: kwota jest za duża.", status=422)
    return int((amount * 100).to_integral_value())


def _spec(body: DocumentBody) -> DocumentSpec:
    lines = [
        engine.clean_line(
            {
                "side": line.side,
                "account": line.account,
                "amount": _grosze(line.amount, index),
                "description": line.description,
                "counterparty_id": line.counterparty_id,
                "mpk": line.mpk,
            },
            index,
        )
        for index, line in enumerate(body.lines, start=1)
    ]
    return DocumentSpec(
        doc_type=body.doc_type,
        op_date=body.op_date,
        doc_date=body.doc_date or body.op_date,
        lines=lines,
        number=body.number,
        description=body.description,
        counterparty_id=body.counterparty_id,
    )


def _config_payload(
    user: User,
    current: ledger_settings.LedgerSettings,
    viewer: Viewer,
    year_list: list[dict[str, Any]],
) -> dict[str, Any]:
    today = business_today()
    return {
        "modules": [
            {
                "key": key,
                "label": ledger_settings.MODULE_LABELS[key],
                "replaces": ledger_settings.MODULE_REPLACES[key],
                "stage": stage,
                "built": key in ledger_settings.BUILT,
                "enabled": current.modules.get(key, False),
                "open": ledger_settings.module_open(user, current, key),
            }
            for key, stage in ledger_settings.MODULES.items()
        ],
        "me": {
            "admin": viewer.admin,
            "approver": viewer.approver,
            "payroll": viewer.payroll,
        },
        "accountants": list(current.accountants) if viewer.admin else None,
        "years": year_list,
        "today": today.isoformat(),
        "doc_types": [
            {"code": code, "label": label, "manual": code in engine.MANUAL_TYPES}
            for code, label in engine.DOC_TYPE_LABELS.items()
        ],
        "year_modes": [
            {"code": code, "label": engine.YEAR_MODE_LABELS[code]}
            for code in YEAR_MODES
        ],
        "account_kinds": list(ACCOUNT_KINDS),
        "account_types": [
            {"code": code, "label": engine.ACCOUNT_TYPE_LABELS[code]}
            for code in ACCOUNT_TYPES
        ],
        "dictionaries": [
            {"code": code, "label": engine.DICTIONARY_LABELS[code]}
            for code in ACCOUNT_DICTIONARIES
        ],
    }


# ── Konfiguracja ─────────────────────────────────────────────────────────────


@router.get("/config")
async def get_config(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    current = await ledger_settings.load(db)
    viewer = documents.viewer_for(current_user, current)
    open_ = ledger_settings.module_open(current_user, current, "ledger")
    year_list = (
        await years.list_years(db, include_payroll=viewer.payroll) if open_ else []
    )
    payload = _config_payload(current_user, current, viewer, year_list)
    payload["open"] = open_
    return payload


@router.put("/config/modules")
async def set_module(
    body: ModuleBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        current = await ledger_settings.set_module(
            db, body.module, body.enabled, actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)


@router.put("/config/accountants")
async def set_accountants(
    body: AccountantsBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _require_admin(current_user)
    try:
        current = await ledger_settings.set_accountants(
            db, body.user_ids, actor=current_user
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return ledger_settings.to_json(current)


@router.get("/config/candidates")
async def accountant_candidates(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _require_admin(current_user)
    users = list(
        (
            await db.scalars(
                select(User).where(User.is_active.is_(True)).order_by(User.name)
            )
        ).all()
    )
    await resolve_effective_access(db, users)
    return {
        "items": [
            {"id": user.id, "name": user.name, "admin": ledger_settings.is_admin(user)}
            for user in users
            if ledger_settings.is_admin(user)
            or has_permission(user, ProductAction.finance_module)
        ]
    }


# ── Rok obrotowy i okresy ────────────────────────────────────────────────────


@router.post("/years", status_code=201)
async def create_year(
    body: YearBody, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    if body.mode != "symfonia":
        _require_admin(current_user)
    try:
        existing = await db.scalar(
            select(LedgerYear.id).where(LedgerYear.year == body.year)
        )
        if existing is not None:
            raise LedgerError(f"Rok obrotowy {body.year} już jest.", status=409)
        await years.ensure_year(db, body.year, actor_id=current_user.id, mode=body.mode)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await years.list_years(db, include_payroll=viewer.payroll)}


@router.patch("/years/{year_id}")
async def update_year(
    year_id: int,
    body: YearPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_admin(current_user)
    try:
        await years.set_mode(db, year_id, body.mode, actor_id=current_user.id)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await years.list_years(db, include_payroll=viewer.payroll)}


@router.post("/periods/{period_id}/close")
async def close_period(
    period_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        await years.close_period(
            db,
            period_id,
            actor_id=current_user.id,
            now=_now(),
            include_payroll=viewer.payroll,
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await years.list_years(db, include_payroll=viewer.payroll)}


@router.post("/periods/{period_id}/reopen")
async def reopen_period(
    period_id: int,
    body: ReopenBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_admin(current_user)
    try:
        await years.reopen_period(
            db, period_id, body.reason, actor_id=current_user.id, now=_now()
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await years.list_years(db, include_payroll=viewer.payroll)}


# ── Dokumenty ────────────────────────────────────────────────────────────────


@router.get("/documents")
async def list_documents(
    current_user: FinanceModuleUser,
    year: int = Query(..., ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month: Optional[int] = Query(None, ge=1, le=12),
    doc_type: Optional[str] = Query(None, pattern=r"^[A-Z]{2,4}$"),
    status_: Optional[Literal["draft", "approved"]] = Query(None, alias="status"),
    q: Optional[str] = Query(None, max_length=80),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=documents.PAGE_MAX),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    return await documents.list_documents(
        db,
        viewer,
        year=year,
        month=month,
        doc_type=doc_type,
        status=status_,
        needle=q,
        offset=offset,
        limit=limit,
    )


@router.post("/documents", status_code=201)
async def create_document(
    body: DocumentBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        doc = await documents.create_draft(db, _spec(body), actor_id=current_user.id)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await documents.document_card(db, viewer, doc.id)


@router.get("/documents/{doc_id}")
async def document_card(
    doc_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        return await documents.document_card(db, viewer, doc_id)
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.patch("/documents/{doc_id}")
async def update_document(
    doc_id: int,
    body: DocumentBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        await documents.update_draft(db, doc_id, _spec(body), viewer=viewer)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await documents.document_card(db, viewer, doc_id)


@router.delete("/documents/{doc_id}", status_code=204)
async def delete_document(
    doc_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> None:
    _, viewer = await _context(db, current_user)
    try:
        await documents.delete_draft(db, doc_id, viewer=viewer)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()


@router.post("/documents/approve")
async def approve_documents(
    body: ApproveBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        result = await documents.approve(db, body.ids, viewer=viewer, now=_now())
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    if not result["approved"] and result["refused"]:
        await db.rollback()
        first = result["refused"][0]
        raise HTTPException(first["status"], first["detail"])
    await db.commit()
    return result


@router.post("/documents/{doc_id}/reverse")
async def reverse_document(
    doc_id: int,
    body: ReverseBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    _require_approver(viewer)
    try:
        storno = await documents.reverse(
            db,
            doc_id,
            viewer=viewer,
            day=body.op_date or business_today(),
            reason=body.reason,
            now=_now(),
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await documents.document_card(db, viewer, storno.id)


# ── Raporty ──────────────────────────────────────────────────────────────────


@router.get("/trial-balance")
async def trial_balance(
    current_user: FinanceModuleUser,
    year: int = Query(..., ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month_from: Optional[int] = Query(None, ge=1, le=12),
    month_to: Optional[int] = Query(None, ge=1, le=12),
    level: Literal["synthetic", "analytic"] = "synthetic",
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        return await reports.trial_balance(
            db, viewer, year=year, month_from=month_from, month_to=month_to, level=level
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


@router.get("/accounts/card")
async def account_card(
    current_user: FinanceModuleUser,
    account: str = Query(..., min_length=1, max_length=ACCOUNT_MAX),
    year: int = Query(..., ge=years.YEAR_MIN, le=years.YEAR_MAX),
    month_from: Optional[int] = Query(None, ge=1, le=12),
    month_to: Optional[int] = Query(None, ge=1, le=12),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        return await reports.account_card(
            db,
            viewer,
            account=clean_account(account, "Konto"),
            year=year,
            month_from=month_from,
            month_to=month_to,
        )
    except LedgerError as exc:
        raise _fail(exc) from exc


# ── Plan kont ────────────────────────────────────────────────────────────────


@router.get("/chart")
async def list_chart(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    return {"items": await chart.list_chart(db, include_payroll=viewer.payroll)}


@router.post("/chart", status_code=201)
async def create_account(
    body: AccountBody,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        await chart.create_account(db, body.model_dump(), actor_id=current_user.id)
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await chart.list_chart(db, include_payroll=viewer.payroll)}


@router.patch("/chart/{account_id}")
async def update_account(
    account_id: int,
    body: AccountPatch,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _, viewer = await _context(db, current_user)
    try:
        await chart.update_account(
            db,
            account_id,
            body.model_dump(exclude_unset=True),
            actor_id=current_user.id,
        )
    except LedgerError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"items": await chart.list_chart(db, include_payroll=viewer.payroll)}
