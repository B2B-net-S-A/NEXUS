"""Faktury z KSeF (Rozliczenia zespołu, R1, R7; makieta M5).

Prefiks ``/api/hr/ksef`` (wpina koordynator w ``app/main.py``). Wszystkie
trasy: moduł „Rozliczenia” (``HrModule.settlements``; admin przechodzi zawsze)
i uprawnienie „Płace” — faktury niosą kwoty wynagrodzeń, więc przełożony,
Kadry bez Płac i osoba z kartoteką ich tu nie widzą (swoją fakturę osoba
widzi w „Moim czasie → Rozliczenie”).

* ``GET /status`` — karta stanu: środowisko, ostatnie pobranie, błędy,
* ``GET /invoices?year=&month=`` — zakładka „Faktury z KSeF” miesiąca,
* ``POST /fetch`` — „Pobierz teraz”, ``POST /refetch`` — „Pobierz ponownie okres”,
* ``POST /invoices/manual`` — faktura spoza KSeF z PDF-em,
* ``GET /invoices/{id}/pdf`` — PDF faktury spoza KSeF,
* ``POST /invoices/{id}/period`` — „Przypisz do miesiąca”,
* ``POST /invoices/{id}/ignore`` — „Pomiń” / „Przywróć”.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.http_headers import content_disposition
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import audit, settlements
from app.services.hr.ksef import invoices, pdf_store, sync
from app.services.hr.modules import HrModule
from app.services.hr.payroll_access import is_payroll
from app.services.hr.payroll_errors import PayrollError
from app.services.hr_settlement_schema import CURRENCIES, REASON_MAX_LENGTH
from app.services.permission_denial import permission_denied

router = APIRouter()


def require_hr_ksef_payroll():
    """Moduł „Rozliczenia” i uprawnienie „Płace” (admin zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.settlements)
        if not is_payroll(current_user):
            raise permission_denied(ProductAction.payroll)
        return current_user

    _check.required_permissions = (ProductAction.payroll,)
    return _check


_payroll = require_hr_ksef_payroll()


def _http(exc: PayrollError) -> HTTPException:
    return HTTPException(exc.status_code, exc.message)


class RefetchIn(BaseModel):
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    #: Tylko faktury tej osoby (jej NIP-u); brak = wszystkie znane NIP-y.
    user_id: Optional[int] = Field(default=None, ge=1)


class PeriodIn(BaseModel):
    year: int = Field(ge=2020, le=2100)
    month: int = Field(ge=1, le=12)
    user_id: Optional[int] = Field(default=None, ge=1)


class IgnoreIn(BaseModel):
    ignored: bool
    reason: Optional[str] = Field(default=None, max_length=REASON_MAX_LENGTH)


@router.get("/status")
async def ksef_status(
    _: User = Depends(_payroll), db: AsyncSession = Depends(get_db)
) -> dict:
    return await invoices.status_payload(db)


@router.get("/invoices")
async def list_invoices(
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
    month: Optional[int] = Query(default=None, ge=1, le=12),
    _: User = Depends(_payroll),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if (year is None) != (month is None):
        raise HTTPException(422, "Podaj rok i miesiąc razem.")
    return await invoices.list_invoices(db, year=year, month=month)


@router.post("/fetch")
async def fetch_now(
    current_user: User = Depends(_payroll), db: AsyncSession = Depends(get_db)
) -> dict:
    try:
        result = await sync.fetch_now(db, actor_id=current_user.id)
    except PayrollError as exc:
        raise _http(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="ksef",
        entity_id=None,
        action="ksef_fetch_now",
        details={k: v for k, v in result.items() if isinstance(v, int)},
    )
    await db.commit()
    return result


@router.post("/refetch")
async def refetch_period(
    payload: RefetchIn,
    current_user: User = Depends(_payroll),
    db: AsyncSession = Depends(get_db),
) -> dict:
    seller_nip: Optional[str] = None
    if payload.user_id is not None:
        billing = await settlements.billing_of(db, payload.user_id)
        if billing is None or not billing.nip:
            raise HTTPException(
                422, "Ta osoba nie ma NIP-u w danych do rozliczeń — najpierw go wpisz."
            )
        seller_nip = billing.nip
    try:
        result = await sync.refetch_period(
            db,
            year=payload.year,
            month=payload.month,
            actor_id=current_user.id,
            seller_nip=seller_nip,
        )
    except PayrollError as exc:
        raise _http(exc) from exc
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=payload.user_id,
        entity_type="ksef",
        entity_id=None,
        action="ksef_refetch_period",
        details={
            "period": f"{payload.year:04d}-{payload.month:02d}",
            **{k: v for k, v in result.items() if isinstance(v, int)},
        },
    )
    await db.commit()
    return result


@router.post("/invoices/manual", status_code=201)
async def add_manual_invoice(
    user_id: int = Form(..., ge=1),
    invoice_number: str = Form(..., min_length=1, max_length=256),
    issue_date: date = Form(...),
    period_year: int = Form(..., ge=2020, le=2100),
    period_month: int = Form(..., ge=1, le=12),
    currency: str = Form("PLN"),
    net_amount: str = Form(..., max_length=32),
    vat_amount: str = Form("0", max_length=32),
    gross_amount: str = Form(..., max_length=32),
    sale_date: Optional[date] = Form(None),
    seller_nip: Optional[str] = Form(None, max_length=32),
    file: UploadFile = File(...),
    current_user: User = Depends(_payroll),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if currency not in CURRENCIES:
        raise HTTPException(422, "Waluta faktury: PLN, EUR albo USD.")
    content = await file.read(pdf_store.MAX_PDF_BYTES + 1)
    try:
        invoice = await invoices.add_manual_pdf(
            db,
            actor=current_user,
            user_id=user_id,
            seller_nip=seller_nip,
            invoice_number=invoice_number,
            issue_date=issue_date,
            sale_date=sale_date,
            period_year=period_year,
            period_month=period_month,
            currency=currency,
            net_amount=net_amount,
            vat_amount=vat_amount,
            gross_amount=gross_amount,
            pdf=content,
        )
    except PayrollError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    [payload] = await invoices.payloads(db, [invoice])
    return payload


@router.get("/invoices/{invoice_id}/pdf")
async def invoice_pdf(
    invoice_id: int, _: User = Depends(_payroll), db: AsyncSession = Depends(get_db)
) -> FileResponse:
    try:
        path = await invoices.pdf_path(db, invoice_id)
    except PayrollError as exc:
        raise _http(exc) from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        headers={
            "Content-Disposition": content_disposition(f"faktura-{invoice_id}.pdf")
        },
    )


@router.post("/invoices/{invoice_id}/period")
async def assign_period(
    invoice_id: int,
    payload: PeriodIn,
    current_user: User = Depends(_payroll),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        invoice = await invoices.assign_period(
            db,
            actor=current_user,
            invoice_id=invoice_id,
            year=payload.year,
            month=payload.month,
            user_id=payload.user_id,
        )
    except PayrollError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    [result] = await invoices.payloads(db, [invoice])
    return result


@router.post("/invoices/{invoice_id}/ignore")
async def ignore_invoice(
    invoice_id: int,
    payload: IgnoreIn,
    current_user: User = Depends(_payroll),
    db: AsyncSession = Depends(get_db),
) -> dict:
    try:
        invoice = await invoices.set_ignored(
            db,
            actor=current_user,
            invoice_id=invoice_id,
            ignored=payload.ignored,
            reason=payload.reason,
        )
    except PayrollError as exc:
        await db.rollback()
        raise _http(exc) from exc
    await db.commit()
    [result] = await invoices.payloads(db, [invoice])
    return result
