"""Faktury w API integracyjnym v1 (``invoices:read`` / ``invoices:write``).

Rejestr faktur NEXUSA (``invoices``, Phase 9 C1): do klienta i od kontraktora,
per kontrakt. Walidacja kwoty i numeru — te same modele co ekran
(``InvoiceCreate`` / ``InvoiceUpdate``: grosze, kwota > 0, numer wymagany).

Różnice wobec ekranu, świadome:

* duplikat (kierunek + numer + kontrakt) → 409 ``duplicate_invoice`` pod
  blokadą doradczą — automatyzacja ponawia żądania, a w tabeli nie ma
  unikalności (dane produkcyjne nieznane, więc bez indeksu);
* zamiast twardego DELETE — ``POST /invoices/{id}/cancel`` (status
  ``cancelled``), bo usunięcie rekordu finansowego przez automat nie
  zostawiałoby śladu;
* każdy zapis zostawia wpis w Historii zdarzeń z kontem serwisowym jako
  autorem (ekran dotąd nie zostawiał żadnego przy edycji).

Moduł NIE MOŻE mieć ``from __future__ import annotations`` (slowapi #579).
"""

import hashlib
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api import invoices as invoice_routes
from app.api.integrations_v1.common import (
    IdPath,
    IntegrationRoute,
    InvoicesRead,
    InvoicesWrite,
    Money,
    Page,
    PageQuery,
    PageSizeQuery,
    dry_run_response,
    idempotent_write,
    integration_actor,
    page_of,
    principal_rate_key,
    read_rate_limit,
    write_rate_limit,
)
from app.core.database import get_db
from app.core.rate_limit import limiter
from app.core.scheduling import business_today
from app.models.contract import Contract
from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus
from app.services.critical_events import record_executed

router = APIRouter(route_class=IntegrationRoute)

_MAX_INT4 = 2_147_483_647


class InvoiceCreateIn(invoice_routes.InvoiceCreate):
    """Model ekranu (walidacja kwoty i numeru) z granicami pól — wartość spoza
    int4 albo za długa waluta dawała 500 z bazy zamiast 422 (przegląd PR 2A),
    a integrator ponawia 5xx."""

    contract_id: int = Field(..., ge=1, le=_MAX_INT4)
    period_month: Optional[int] = Field(None, ge=1, le=12)
    period_year: Optional[int] = Field(None, ge=2000, le=2100)
    pdf_document_id: Optional[int] = Field(None, ge=1, le=_MAX_INT4)
    currency: str = Field("PLN", min_length=3, max_length=3)
    notes: Optional[str] = Field(None, max_length=2000)


class InvoiceUpdateIn(invoice_routes.InvoiceUpdate):
    period_month: Optional[int] = Field(None, ge=1, le=12)
    period_year: Optional[int] = Field(None, ge=2000, le=2100)
    pdf_document_id: Optional[int] = Field(None, ge=1, le=_MAX_INT4)
    currency: Optional[str] = Field(None, min_length=3, max_length=3)
    notes: Optional[str] = Field(None, max_length=2000)


class InvoiceOut(BaseModel):
    id: int
    contract_id: int
    direction: str
    invoice_number: str
    period_year: Optional[int]
    period_month: Optional[int]
    issue_date: date
    due_date: Optional[date]
    paid_date: Optional[date]
    amount: Money
    currency: str
    status: str
    notes: Optional[str]
    created_at: datetime
    updated_at: datetime


def invoice_out(inv: Invoice) -> InvoiceOut:
    return InvoiceOut(
        id=inv.id,
        contract_id=inv.contract_id,
        direction=getattr(inv.direction, "value", inv.direction),
        invoice_number=inv.invoice_number,
        period_year=inv.period_year,
        period_month=inv.period_month,
        issue_date=inv.issue_date,
        due_date=inv.due_date,
        paid_date=inv.paid_date,
        amount=inv.amount,
        currency=inv.currency,
        status=getattr(inv.status, "value", inv.status),
        notes=inv.notes,
        created_at=inv.created_at,
        updated_at=inv.updated_at,
    )


# ── Odczyt ───────────────────────────────────────────────────────────────────


@router.get("/invoices", response_model=Page[InvoiceOut], summary="Rejestr faktur")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def list_invoices(
    request: Request,
    _caller: InvoicesRead,
    db: AsyncSession = Depends(get_db),
    page: PageQuery = 1,
    page_size: PageSizeQuery = 200,
    contract_id: Optional[int] = Query(None, ge=1, le=_MAX_INT4),
    status: Optional[InvoiceStatus] = Query(None),
    direction: Optional[InvoiceDirection] = Query(None),
    issued_from: Optional[date] = Query(None),
    issued_to: Optional[date] = Query(None),
    overdue_only: bool = Query(False),
    updated_since: Optional[datetime] = Query(None),
) -> dict:
    """Faktury sortowane po id. ``overdue_only`` = wystawione/wysłane po terminie."""
    query = select(Invoice)
    if contract_id is not None:
        query = query.where(Invoice.contract_id == contract_id)
    if status is not None:
        query = query.where(Invoice.status == status)
    if direction is not None:
        query = query.where(Invoice.direction == direction)
    if issued_from is not None:
        query = query.where(Invoice.issue_date >= issued_from)
    if issued_to is not None:
        query = query.where(Invoice.issue_date <= issued_to)
    if overdue_only:
        query = query.where(
            Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.sent]),
            Invoice.due_date.isnot(None),
            Invoice.due_date < business_today(),
        )
    if updated_since is not None:
        query = query.where(Invoice.updated_at >= updated_since)
    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar() or 0
    rows = (
        (
            await db.execute(
                query.order_by(Invoice.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        )
        .scalars()
        .all()
    )
    return page_of(
        [invoice_out(r) for r in rows], page=page, page_size=page_size, total=total
    )


@router.get(
    "/invoices/dso",
    response_model=list[invoice_routes.DsoRow],
    summary="DSO per klient (PLN)",
)
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def invoices_dso(
    request: Request,
    _caller: InvoicesRead,
    db: AsyncSession = Depends(get_db),
) -> list:
    """Średni czas spływu należności per klient (faktury do klienta, w PLN)."""
    # Trasa ekranu nie czyta użytkownika — wołamy ją wprost.
    return await invoice_routes.dso_by_client(current_user=None, db=db)


@router.get("/invoices/{invoice_id}", response_model=InvoiceOut, summary="Faktura")
@limiter.limit(read_rate_limit, key_func=principal_rate_key)
async def get_invoice(
    request: Request,
    invoice_id: IdPath,
    _caller: InvoicesRead,
    db: AsyncSession = Depends(get_db),
) -> InvoiceOut:
    inv = await db.get(Invoice, invoice_id)
    if inv is None:
        raise HTTPException(404, detail="Faktura nie istnieje.")
    return invoice_out(inv)


# ── Zapis ────────────────────────────────────────────────────────────────────


async def _lock_number(
    db: AsyncSession, direction: str, number: str, contract_id: int
) -> None:
    key = int.from_bytes(
        hashlib.sha256(f"invoice:{direction}:{contract_id}:{number}".encode()).digest()[
            :8
        ],
        "big",
        signed=True,
    )
    await db.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})


async def _assert_no_duplicate(
    db: AsyncSession,
    *,
    direction: str,
    number: str,
    contract_id: int,
    exclude_id: Optional[int] = None,
) -> None:
    await _lock_number(db, direction, number, contract_id)
    query = select(Invoice.id).where(
        Invoice.direction == direction,
        Invoice.contract_id == contract_id,
        func.lower(func.btrim(Invoice.invoice_number)) == number.strip().lower(),
    )
    if exclude_id is not None:
        query = query.where(Invoice.id != exclude_id)
    existing = await db.scalar(query.limit(1))
    if existing is not None:
        raise HTTPException(
            409,
            detail={
                "error": "duplicate_invoice",
                "message": "Faktura o tym numerze i kierunku już istnieje dla tego kontraktu.",
                "invoice_id": existing,
            },
        )


@router.post(
    "/invoices",
    response_model=InvoiceOut,
    status_code=201,
    summary="Wystaw fakturę w rejestrze",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def create_invoice(
    request: Request,
    body: InvoiceCreateIn,
    caller: InvoicesWrite,
    db: AsyncSession = Depends(get_db),
    dry_run: bool = Query(False, description="Tylko walidacja, bez zapisu."),
) -> Response:
    data = body.model_dump()

    async def run():
        contract = await db.get(Contract, body.contract_id)
        if contract is None:
            raise HTTPException(404, detail="Kontrakt nie istnieje.")
        direction = getattr(body.direction, "value", body.direction)
        await _assert_no_duplicate(
            db,
            direction=direction,
            number=body.invoice_number,
            contract_id=body.contract_id,
        )
        if dry_run:
            return 200, {"valid": True}
        inv = Invoice(**data, created_by=None)
        db.add(inv)
        await db.flush()
        await db.refresh(inv)
        await record_executed(
            db,
            actor=integration_actor(caller),
            event_type="invoice.create",
            entity_type="invoice",
            entity_id=inv.id,
            entity_label=f"Faktura {inv.invoice_number}",
            client_id=contract.client_id,
            details={"contract_id": contract.id, "direction": direction},
        )
        return 201, invoice_out(inv)

    if dry_run:
        return await dry_run_response(db, run)
    return await idempotent_write(request, db, caller, payload=data, run=run)


@router.patch(
    "/invoices/{invoice_id}", response_model=InvoiceOut, summary="Zmień fakturę"
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def update_invoice(
    request: Request,
    invoice_id: IdPath,
    body: InvoiceUpdateIn,
    caller: InvoicesWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Zmiana pól faktury (np. ``paid_date`` + ``status=paid`` po zapłacie)."""
    changes = body.model_dump(exclude_unset=True)

    async def run():
        inv = await db.scalar(
            select(Invoice).where(Invoice.id == invoice_id).with_for_update()
        )
        if inv is None:
            raise HTTPException(404, detail="Faktura nie istnieje.")
        new_direction = changes.get("direction", inv.direction)
        direction = getattr(new_direction, "value", new_direction)
        number = changes.get("invoice_number", inv.invoice_number)
        if "direction" in changes or "invoice_number" in changes:
            await _assert_no_duplicate(
                db,
                direction=direction,
                number=number,
                contract_id=inv.contract_id,
                exclude_id=inv.id,
            )
        before = {k: getattr(inv, k) for k in changes}
        for key, value in changes.items():
            setattr(inv, key, value)
        await db.flush()
        await db.refresh(inv)
        contract = await db.get(Contract, inv.contract_id)
        await record_executed(
            db,
            actor=integration_actor(caller),
            event_type="invoice.update",
            entity_type="invoice",
            entity_id=inv.id,
            entity_label=f"Faktura {inv.invoice_number}",
            client_id=getattr(contract, "client_id", None),
            details={
                "changed": sorted(changes),
                "before": {k: str(getattr(v, "value", v)) for k, v in before.items()},
            },
        )
        return 200, invoice_out(inv)

    return await idempotent_write(
        request, db, caller, payload={"id": invoice_id, **changes}, run=run
    )


class CancelIn(BaseModel):
    reason: str = Field(..., min_length=3, max_length=500)


@router.post(
    "/invoices/{invoice_id}/cancel",
    response_model=InvoiceOut,
    summary="Anuluj fakturę (status cancelled)",
)
@limiter.limit(write_rate_limit, key_func=principal_rate_key)
async def cancel_invoice(
    request: Request,
    invoice_id: IdPath,
    body: CancelIn,
    caller: InvoicesWrite,
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Anulowanie zamiast usunięcia — rekord zostaje z powodem w Historii zdarzeń."""

    async def run():
        inv = await db.scalar(
            select(Invoice).where(Invoice.id == invoice_id).with_for_update()
        )
        if inv is None:
            raise HTTPException(404, detail="Faktura nie istnieje.")
        inv.status = InvoiceStatus.cancelled
        await db.flush()
        await db.refresh(inv)
        contract = await db.get(Contract, inv.contract_id)
        await record_executed(
            db,
            actor=integration_actor(caller),
            event_type="invoice.cancel",
            entity_type="invoice",
            entity_id=inv.id,
            entity_label=f"Faktura {inv.invoice_number}",
            client_id=getattr(contract, "client_id", None),
            reason=body.reason,
        )
        return 200, invoice_out(inv)

    return await idempotent_write(
        request, db, caller, payload={"id": invoice_id, "reason": body.reason}, run=run
    )
