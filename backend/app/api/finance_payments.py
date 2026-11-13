"""Finanse → „Przelewy” (księgowość E3, 0696): paczki przelewów kosztów i zapłaty.

Prefiks ``/api/finance/payments`` (``app/main.py``, za wyłącznikiem programu
„Ludzi w NEXUSIE”). Bramki jak w „Kosztach”: sekcja Finanse (router),
uprawnienie „Moduł Finanse” (``FinanceModuleUser``) i moduł „Księgowość”
(``app_settings['finance_accounting']``; wyłączony = 404, admin widzi zawsze).
Faktury osób zespołu (nazwisko, kwota) tylko z Płacami (D2): poza Płacami
nie ma ich w planie, sumach, pliku ani na karcie (404).

Serwis: ``services/finance_ledger/payments.py``.

* ``GET/PUT /settings`` — rachunek i nazwa nadawcy (plik Elixir),
* ``POST /plan`` — faktury do zapłaty do daty z trybem, tytułem i białą listą,
* ``GET /batches``, ``POST /batches``, ``GET /batches/{id}``,
  ``GET /batches/{id}/file``, ``POST /batches/{id}/cancel`` — paczki,
* ``POST /statements``, ``GET /statements``, ``POST /records/{id}/assign``,
  ``POST /records/{id}/ignore`` — obciążenia z wyciągu,
* ``GET/PUT /entries/{id}``, ``POST /entries/{id}/paid`` — płatność na karcie.
"""

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Optional

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import FinanceModuleUser
from app.api.finance_ledger import _open
from app.api.section_access import FINANCE_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.services.finance_ledger import payments
from app.services.hr.bank import statements
from app.services.hr.bank.parsed import StatementError
from app.services.hr.payroll_access import is_payroll

router = APIRouter(dependencies=FINANCE_SECTION_DEPENDENCIES)


class CostPaymentSettingsIn(BaseModel):
    sender_name: str = Field(min_length=1, max_length=255)
    sender_account: str = Field(min_length=1, max_length=64)


class CostPaymentPlanIn(BaseModel):
    until: Optional[date] = None


class CostPaymentBatchIn(BaseModel):
    entry_ids: list[int] = Field(min_length=1, max_length=payments.BULK_MAX)
    acknowledged: list[int] = Field(default_factory=list, max_length=payments.BULK_MAX)
    execution_date: Optional[date] = None
    format: Optional[Literal["elixir", "csv"]] = None


class CostPaymentAccountIn(BaseModel):
    account: Optional[str] = Field(default=None, max_length=64)
    remember: bool = True


class CostPaymentPaidIn(BaseModel):
    amount: Optional[Decimal] = Field(
        default=None, gt=0, max_digits=14, decimal_places=2
    )
    paid_on: date
    reason: str = Field(min_length=1, max_length=500)


class CostPaymentAssignIn(BaseModel):
    entry_id: int = Field(gt=0)


class CostPaymentIgnoreIn(BaseModel):
    reason: str = Field(min_length=1, max_length=500)


def _fail(exc: payments.PaymentError) -> HTTPException:
    return HTTPException(exc.status, exc.detail())


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Ustawienia ───────────────────────────────────────────────────────────────


@router.get("/settings")
async def get_settings(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await payments.load_settings(db)


@router.put("/settings")
async def put_settings(
    body: CostPaymentSettingsIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        value = await payments.save_settings(
            db,
            sender_name=body.sender_name,
            sender_account=body.sender_account,
            actor_id=current_user.id,
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return value


# ── Plan i paczki ────────────────────────────────────────────────────────────


@router.post("/plan")
async def payment_plan(
    body: CostPaymentPlanIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Plan paczki; POST, bo sprawdza rachunki w wykazie VAT (limit dzienny)."""

    await _open(db, current_user)
    today = business_today()
    items = await payments.plan(
        db,
        until=body.until or today,
        today=today,
        actor_id=current_user.id,
        payroll=is_payroll(current_user),
    )
    # Ślad zapytań do białej listy (hr_audit_events) zostaje.
    await db.commit()
    return {
        "until": (body.until or today).isoformat(),
        "items": [payments.item_payload(item) for item in items],
        **payments.plan_summary(items),
    }


@router.get("/batches")
async def batches(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return {"items": await payments.list_batches(db)}


@router.post("/batches")
async def create_batch(
    body: CostPaymentBatchIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        result = await payments.create_batch(
            db,
            entry_ids=body.entry_ids,
            acknowledged=body.acknowledged,
            execution_date=body.execution_date,
            fmt=body.format,
            today=business_today(),
            actor_id=current_user.id,
            payroll=is_payroll(current_user),
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


@router.get("/batches/{batch_id}")
async def batch_detail(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await payments.batch_detail(
            db, batch_id, payroll=is_payroll(current_user)
        )
    except payments.PaymentError as exc:
        raise _fail(exc) from exc


@router.get("/batches/{batch_id}/file")
async def batch_file(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> Response:
    await _open(db, current_user)
    try:
        name, content, media = await payments.batch_file(
            db, batch_id, payroll=is_payroll(current_user), actor_id=current_user.id
        )
    except payments.PaymentError as exc:
        raise _fail(exc) from exc
    return Response(
        content=content,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{name}"',
            "Cache-Control": "no-store",
        },
    )


@router.post("/batches/{batch_id}/cancel")
async def cancel_batch(
    batch_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        result = await payments.cancel_batch(
            db,
            batch_id,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return result


# ── Wyciąg ───────────────────────────────────────────────────────────────────


@router.post("/statements")
async def upload_statement(
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(..., description="Wyciąg MT940 albo CAMT.053"),
) -> dict[str, Any]:
    """Obciążenia → zapłaty faktur kosztowych (zespół zostaje Płacom, uznania
    — „Fakturom do klientów”)."""

    await _open(db, current_user)
    raw = await file.read(statements.MAX_STATEMENT_BYTES + 1)
    try:
        result = await payments.import_debits(db, raw, actor_id=current_user.id)
    except StatementError as exc:
        await db.rollback()
        raise HTTPException(422, str(exc)) from exc
    await db.commit()
    return result.as_dict()


@router.get("/statements")
async def statement_overview(
    current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    return await payments.statement_overview(db)


@router.post("/records/{record_id}/assign")
async def assign_record(
    record_id: int,
    body: CostPaymentAssignIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await payments.assign_record(
            db,
            record_id,
            body.entry_id,
            actor_id=current_user.id,
            now=_now(),
            payroll=is_payroll(current_user),
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"id": record_id, "entry_id": body.entry_id, "match_status": "matched"}


@router.post("/records/{record_id}/ignore")
async def ignore_record(
    record_id: int,
    body: CostPaymentIgnoreIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        await payments.ignore_record(
            db, record_id, reason=body.reason, actor_id=current_user.id, now=_now()
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return {"id": record_id, "match_status": "ignored"}


# ── Płatność na karcie faktury ───────────────────────────────────────────────


@router.get("/entries/{entry_id}")
async def entry_payment(
    entry_id: int, current_user: FinanceModuleUser, db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    await _open(db, current_user)
    try:
        return await payments.entry_card(db, entry_id, payroll=is_payroll(current_user))
    except payments.PaymentError as exc:
        raise _fail(exc) from exc


@router.put("/entries/{entry_id}")
async def entry_account(
    entry_id: int,
    body: CostPaymentAccountIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    payroll = is_payroll(current_user)
    try:
        await payments.set_account(
            db,
            entry_id,
            account=body.account,
            remember=body.remember,
            actor_id=current_user.id,
            payroll=payroll,
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await payments.entry_card(db, entry_id, payroll=payroll)


@router.post("/entries/{entry_id}/paid")
async def entry_paid(
    entry_id: int,
    body: CostPaymentPaidIn,
    current_user: FinanceModuleUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    await _open(db, current_user)
    if body.paid_on > business_today():
        raise HTTPException(422, "Data zapłaty nie może być z przyszłości.")
    payroll = is_payroll(current_user)
    try:
        await payments.mark_paid(
            db,
            entry_id,
            amount=body.amount,
            paid_on=body.paid_on,
            reason=body.reason,
            actor_id=current_user.id,
            now=_now(),
            payroll=payroll,
        )
    except payments.PaymentError as exc:
        await db.rollback()
        raise _fail(exc) from exc
    await db.commit()
    return await payments.entry_card(db, entry_id, payroll=payroll)
