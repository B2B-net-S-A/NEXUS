"""Phase 9 C1 — invoice ledger + DSO reporting + CSV export."""

import csv
import logging
from datetime import date
from decimal import Decimal
from io import StringIO
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, PlainSerializer
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.financial_access import FinanceManageUser, FinanceReadUser
from app.core.database import get_db
from app.models.client import Client
from app.models.contract import Contract
from app.models.invoice import Invoice, InvoiceDirection, InvoiceStatus
from app.services.client_identity import client_display_name_expression
from app.services.fx_service import rates_to_pln

logger = logging.getLogger(__name__)

router = APIRouter()


def _money_out(value: Decimal) -> float:
    """Serialize a money Decimal as a JSON number (grosze precision).

    A bare ``Decimal`` DTO field serializes as a JSON *string* under Pydantic v2,
    which would make the frontend's numeric ``reduce()``/``sum()`` over these
    totals concatenate strings and corrupt the figures. Emit a float instead.
    """
    return float(Decimal(value).quantize(Decimal("0.01")))


# Exact Decimal internally; JSON number on the wire (see `_money_out`).
MoneyPLN = Annotated[
    Decimal, PlainSerializer(_money_out, return_type=float, when_used="json")
]

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
    total_amount: MoneyPLN
    paid_amount: MoneyPLN
    outstanding: MoneyPLN
    avg_dso_days: Optional[float]
    # All amounts are normalised to PLN. `fx_incomplete` flags a client that has
    # invoices in a currency with no cached FX rate — those amounts are excluded
    # from the PLN totals rather than added at face value (additive fields; the
    # frontend ignores unknown keys).
    currency: str = "PLN"
    fx_incomplete: bool = False


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("", response_model=List[InvoiceResponse])
async def list_invoices(
    current_user: FinanceReadUser,
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
    current_user: FinanceManageUser,
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
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Per-client Days Sales Outstanding aggregates (client-facing invoices).

    Amounts are normalised to PLN: each invoice carries its own ``currency``, so
    summing the raw ``Invoice.amount`` integers across currencies is meaningless.
    We aggregate per client × currency in SQL, then convert each subtotal to PLN
    with today's report rate before folding into the per-client total.
    """
    today = date.today()
    client_name = client_display_name_expression()

    # Totals per client × currency (client-facing invoices).
    total_rows = (
        await db.execute(
            select(
                Client.id,
                client_name.label("client_name"),
                Invoice.currency,
                func.count(Invoice.id).label("cnt"),
                func.coalesce(func.sum(Invoice.amount), 0).label("total"),
            )
            .join(Contract, Contract.client_id == Client.id)
            .join(Invoice, Invoice.contract_id == Contract.id)
            .where(Invoice.direction == InvoiceDirection.to_client)
            .group_by(Client.id, client_name, Invoice.currency)
        )
    ).all()

    # Paid totals per client × currency.
    paid_rows = (
        await db.execute(
            select(
                Client.id,
                Invoice.currency,
                func.coalesce(func.sum(Invoice.amount), 0).label("paid"),
            )
            .join(Contract, Contract.client_id == Client.id)
            .join(Invoice, Invoice.contract_id == Contract.id)
            .where(
                Invoice.direction == InvoiceDirection.to_client,
                Invoice.status == InvoiceStatus.paid,
            )
            .group_by(Client.id, Invoice.currency)
        )
    ).all()
    paid_by: dict[tuple[int, str], int] = {
        (r.id, (r.currency or "PLN").upper()): int(r.paid or 0) for r in paid_rows
    }

    currencies = {(r.currency or "PLN").upper() for r in total_rows}
    rates = await rates_to_pln(db, currencies, today)

    acc: dict[int, dict] = {}
    for r in total_rows:
        cur = (r.currency or "PLN").upper()
        bucket = acc.setdefault(
            r.id,
            {
                "client_name": r.client_name,
                "invoices": 0,
                "total": Decimal("0"),
                "paid": Decimal("0"),
                "fx_incomplete": False,
            },
        )
        bucket["invoices"] += int(r.cnt or 0)
        rate = rates.get(cur)
        if rate is None:
            bucket["fx_incomplete"] = True
            logger.warning(
                "invoices/dso: no FX rate for %s (client_id=%s) — excluded from PLN total",
                cur,
                r.id,
            )
            continue
        bucket["total"] += Decimal(int(r.total or 0)) * rate
        bucket["paid"] += Decimal(paid_by.get((r.id, cur), 0)) * rate

    rows: list[DsoRow] = []
    for client_id, bucket in acc.items():
        # avg DSO days is a time metric — currency-agnostic, so it stays a plain
        # per-client aggregate over all paid client-facing invoices.
        per_client = await db.execute(
            select(Invoice.issue_date, Invoice.paid_date).where(
                Invoice.contract_id.in_(
                    select(Contract.id).where(Contract.client_id == client_id)
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
        outstanding = bucket["total"] - bucket["paid"]
        if outstanding < 0:
            outstanding = Decimal("0")
        rows.append(
            DsoRow(
                client_id=client_id,
                client_name=bucket["client_name"],
                invoices=bucket["invoices"],
                total_amount=bucket["total"],
                paid_amount=bucket["paid"],
                outstanding=outstanding,
                avg_dso_days=avg_dso,
                currency="PLN",
                fx_incomplete=bucket["fx_incomplete"],
            )
        )
    # Preserve the original ordering: most-invoiced clients first.
    rows.sort(key=lambda x: x.invoices, reverse=True)
    return rows


@router.get("/export.csv")
async def export_invoices_csv(
    current_user: FinanceReadUser,
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
    current_user: FinanceReadUser,
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
    current_user: FinanceManageUser,
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
    current_user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    inv = await db.scalar(select(Invoice).where(Invoice.id == invoice_id))
    if not inv:
        raise HTTPException(status_code=404, detail="Invoice not found")
    await db.delete(inv)
