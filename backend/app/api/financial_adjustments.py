"""Korekty finansowe — API (plan PR 6).

- POST ""            — utworzenie draftu (finance/admin),
- POST /{id}/approve — zatwierdzenie (admin; jedyna dozwolona zmiana),
- GET  ""            — lista (finance/admin).

Brak PATCH/DELETE z założenia: rejestr jest niemutowalnym audit trailem.
Pomyłkę koryguje się KOLEJNĄ korektą (storno), nie edycją historii.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.financial_access import (
    FinanceApproveUser,
    FinanceManageUser,
    FinanceReadUser,
)
from app.core.database import get_db
from app.models.financial_adjustment import AdjustmentStatus, FinancialAdjustment

router = APIRouter()


class AdjustmentCreate(BaseModel):
    effective_month: date
    kind: str = Field(min_length=2, max_length=50)
    # Kwota jako string → Decimal (zero strat precyzji po drodze przez JSON).
    amount: Decimal
    currency: str = Field(default="PLN", min_length=3, max_length=3)
    description: str = Field(min_length=3)
    client_id: Optional[int] = None


class AdjustmentRead(BaseModel):
    id: int
    effective_month: date
    kind: str
    amount: str
    currency: str
    description: str
    client_id: Optional[int]
    status: AdjustmentStatus
    created_by: int
    created_at: datetime
    approved_by: Optional[int]
    approved_at: Optional[datetime]


def _to_read(a: FinancialAdjustment) -> AdjustmentRead:
    return AdjustmentRead(
        id=a.id,
        effective_month=a.effective_month,
        kind=a.kind,
        amount=str(a.amount),
        currency=a.currency,
        description=a.description,
        client_id=a.client_id,
        status=a.status,
        created_by=a.created_by,
        created_at=a.created_at,
        approved_by=a.approved_by,
        approved_at=a.approved_at,
    )


@router.get("", response_model=list[AdjustmentRead])
async def list_adjustments(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[AdjustmentStatus] = Query(None, alias="status"),
    limit: int = Query(100, ge=1, le=500),
):
    stmt = select(FinancialAdjustment).order_by(
        FinancialAdjustment.effective_month.desc(), FinancialAdjustment.id.desc()
    )
    if status_filter is not None:
        stmt = stmt.where(FinancialAdjustment.status == status_filter)
    rows = (await db.execute(stmt.limit(limit))).scalars().all()
    return [_to_read(a) for a in rows]


@router.post("", response_model=AdjustmentRead, status_code=status.HTTP_201_CREATED)
async def create_adjustment(
    payload: AdjustmentCreate,
    current_user: FinanceManageUser,
    db: AsyncSession = Depends(get_db),
):
    adjustment = FinancialAdjustment(
        effective_month=payload.effective_month.replace(day=1),
        kind=payload.kind,
        amount=payload.amount,
        currency=payload.currency.upper(),
        description=payload.description,
        client_id=payload.client_id,
        status=AdjustmentStatus.draft,
        created_by=current_user.id,
    )
    db.add(adjustment)
    await db.commit()
    await db.refresh(adjustment)
    return _to_read(adjustment)


@router.post("/{adjustment_id}/approve", response_model=AdjustmentRead)
async def approve_adjustment(
    adjustment_id: int,
    current_user: FinanceApproveUser,
    db: AsyncSession = Depends(get_db),
):
    # Approval is deliberately separated from Finance preparation. Only Admin
    # carries APPROVE_FINANCE, while immutable audit fields preserve the full
    # decision trail.
    adjustment = await db.get(FinancialAdjustment, adjustment_id)
    if adjustment is None:
        raise HTTPException(404, detail="Adjustment not found")
    if adjustment.status is AdjustmentStatus.approved:
        raise HTTPException(409, detail="Adjustment already approved (immutable)")
    adjustment.status = AdjustmentStatus.approved
    adjustment.approved_by = current_user.id
    adjustment.approved_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(adjustment)
    return _to_read(adjustment)
