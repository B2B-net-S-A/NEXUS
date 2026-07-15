"""Phase 9 C1 — invoice ledger + DSO reporting + CSV export."""

from datetime import date
from io import StringIO
import csv
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, TacPlus
from app.core.database import get_db
from app.models.client import Client
from app.models.contract import Contract
from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus

router = APIRouter()


# ── Pydantic DTOs ────────────────────────────────────────────────────────────


class InvoiceBase(BaseModel):
    direction: InvoiceDirection
    invoice_number: str
    period_month: Optional[int] = None
    period_year: Optional[int] = None
    issue_date: date
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    amount: int
    currency: str = "PLN"
    status: InvoiceStatus = InvoiceStatus.issued
    pdf_document_id: Optional[int] = None
    notes: Optional[str] = None


class InvoiceCreate(InvoiceBase):
    contract_id: int


class InvoiceUpdate(BaseModel):
    direction: Optional[InvoiceDirection] = None
    invoice_number: Optional[str] = None
    period_month: Optional[int] = None
    period_year: Optional[int] = None
    issue_date: Optional[date] = None
    due_date: Optional[date] = None
    paid_date: Optional[date] = None
    amount: Optional[int] = None
    currency: Optional[str] = None
    status: Optional[InvoiceStatus] = None
    pdf_document_id: Optional[int] = None
    notes: Optional[str] = None


class InvoiceResponse(InvoiceBase):
    id: int
    contract_id: int

    model_config = {"from_attributes": True}


class DsoRow(BaseModel):
    client_id: int
    client_name: str
    invoices: int
    total_amount: int
    paid_amount: int
    outstanding: int
    avg_dso_days: Optional[float]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=List[InvoiceResponse])
async def list_invoices(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    contract_id: Optional[int] = Query(None),
    status_filter: Optional[InvoiceStatus] = Query(None, alias="status"),
    direction: Optional[InvoiceDirection] = Query(None),
    overdue_only: bool = Query(False),
):
    query = select(Invoice)
    if contract_id is not None:
        query = query.where(Invoice.contract_id == contract_id)
    if status_filter:
        query = query.where(Invoice.status == status_filter)
    if direction:
        query = query.where(Invoice.direction == direction)
    if overdue_only:
        today = date.today()
        query = query.where(
            Invoice.status.in_([InvoiceStatus.issued, InvoiceStatus.sent]),
            Invoice.due_date.isnot(None),
            Invoice.due_date < today,
        )
    query = query.order_by(Invoice.issue_date.desc(), Invoice.id.desc())
    res = await db.execute(query)
    return list(res.scalars().all())


@router.post("", response_model=InvoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_invoice(
    data: InvoiceCreate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    contract = await db.scalar(select(Contract).where(Contract.id == data.contract_id))
    if not contract:
        raise HTTPException(status_code=404, detail="Contract not found")
    inv = Invoice(**data.model_dump(), created_by=current_user.id)
    db.add(inv)
    await db.flush()
    await db.refresh(inv)
    return inv


@router.get("/dso", response_model=List[DsoRow])
async def dso_by_client(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Per-client Days Sales Outstanding aggregates (client-facing invoices)."""
    res = await db.execute(
        select(
            Client.id,
            Client.name,
            func.count(Invoice.id).label("cnt"),
            func.coalesce(func.sum(Invoice.amount), 0).label("total"),
        )
        .join(Contract, Contract.client_id == Client.id)
        .join(Invoice, Invoice.contract_id == Contract.id)
        .where(Invoice.direction == InvoiceDirection.to_client)
        .group_by(Client.id, Client.name)
        .order_by(func.count(Invoice.id).desc())
    )
    rows: list[DsoRow] = []
    for r in res.all():
        # Paid sum via a separate targeted query — simpler than CASE WHEN.
        paid_res = await db.execute(
            select(func.coalesce(func.sum(Invoice.amount), 0)).where(
                Invoice.contract_id.in_(
                    select(Contract.id).where(Contract.client_id == r.id)
                ),
                Invoice.direction == InvoiceDirection.to_client,
                Invoice.status == InvoiceStatus.paid,
            )
        )
        paid_sum = int(paid_res.scalar() or 0)

        per_client = await db.execute(
            select(Invoice.issue_date, Invoice.paid_date).where(
                Invoice.contract_id.in_(
                    select(Contract.id).where(Contract.client_id == r.id)
                ),
                Invoice.direction == InvoiceDirection.to_client,
                Invoice.paid_date.isnot(None),
            )
        )
        diffs = [
            (paid - issue).days
            for issue, paid in per_client.all()
            if paid is not None and issue is not None and paid >= issue
        ]
        avg_dso = round(sum(diffs) / len(diffs), 1) if diffs else None
        total = int(r.total or 0)
        rows.append(
            DsoRow(
                client_id=r.id,
                client_name=r.name,
                invoices=r.cnt,
                total_amount=total,
                paid_amount=paid_sum,
                outstanding=max(0, total - paid_sum),
                avg_dso_days=avg_dso,
            )
        )
    return rows


@router.get("/export.csv")
async def export_invoices_csv(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """CSV export in a format compatible with Fakturownia/iFirma."""
    res = await db.execute(select(Invoice).order_by(Invoice.issue_date.desc()))
    rows = list(res.scalars().all())
    buf = StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(
        [
            "Numer",
            "Data wystawienia",
            "Termin",
            "Data zaplaty",
            "Kwota",
            "Waluta",
            "Kontrakt",
            "Kierunek",
            "Status",
            "Okres",
        ]
    )
    for inv in rows:
        period = (
            f"{inv.period_year}-{inv.period_month:02d}"
            if inv.period_month and inv.period_year
            else ""
        )
        writer.writerow(
            [
                inv.invoice_number,
                inv.issue_date.isoformat(),
                inv.due_date.isoformat() if inv.due_date else "",
                inv.paid_date.isoformat() if inv.paid_date else "",
                inv.amount,
                inv.currency,
                inv.contract_id,
                inv.direction.value,
                inv.status.value,
                period,
            ]
        )
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="invoices.csv"'},
    )


@router.get("/{invoice_id}", response_model=InvoiceResponse)
async def get_invoice(
    invoice_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    inv = await db.scalar(select(Invoice).where(Invoice.id == invoice_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    return inv


@router.patch("/{invoice_id}", response_model=InvoiceResponse)
async def update_invoice(
    invoice_id: int,
    data: InvoiceUpdate,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    inv = await db.scalar(select(Invoice).where(Invoice.id == invoice_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(inv, k, v)
    await db.flush()
    await db.refresh(inv)
    return inv


@router.delete("/{invoice_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_invoice(
    invoice_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    inv = await db.scalar(select(Invoice).where(Invoice.id == invoice_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    await db.delete(inv)
