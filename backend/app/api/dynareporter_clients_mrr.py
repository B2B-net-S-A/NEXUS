"""DynaReporter B.2.5 — Clients + MRR + Finances endpoints (readonly)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.dr_clients_mrr import DrClient, DrClientMrr, DrFinance

router = APIRouter()


class ClientResponse(BaseModel):
    id: int
    name: str
    is_active: bool


class ClientMrrResponse(BaseModel):
    client_id: int
    client_name: Optional[str] = None
    report_month: date
    consultants_count: int
    mrr: Decimal


class FinanceResponse(BaseModel):
    report_month: date
    total_revenue: Decimal
    total_costs: Decimal
    profit: Decimal  # revenue - costs
    cv_database_count: int
    consultants_churn: int
    department: Optional[str] = None


class MrrSummary(BaseModel):
    from_month: date
    to_month: date
    total_mrr: Decimal
    avg_consultants: float
    distinct_clients: int


@router.get("/clients", response_model=list[ClientResponse])
async def list_clients(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    only_active: bool = Query(default=True),
) -> list[ClientResponse]:
    stmt = select(DrClient)
    if only_active:
        stmt = stmt.where(DrClient.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(DrClient.name))).scalars().all()
    return [ClientResponse.model_validate(r.__dict__) for r in rows]


@router.get("/mrr", response_model=list[ClientMrrResponse])
async def list_mrr(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    client_id: Optional[int] = Query(default=None),
    from_month: Optional[date] = Query(default=None),
    to_month: Optional[date] = Query(default=None),
) -> list[ClientMrrResponse]:
    stmt = select(
        DrClientMrr.client_id,
        DrClient.name,
        DrClientMrr.report_month,
        DrClientMrr.consultants_count,
        DrClientMrr.mrr,
    ).outerjoin(DrClient, DrClient.id == DrClientMrr.client_id)
    if client_id:
        stmt = stmt.where(DrClientMrr.client_id == client_id)
    if from_month:
        stmt = stmt.where(DrClientMrr.report_month >= from_month)
    if to_month:
        stmt = stmt.where(DrClientMrr.report_month <= to_month)
    rows = (await db.execute(stmt.order_by(DrClientMrr.report_month.desc()))).all()
    return [
        ClientMrrResponse(
            client_id=cid,
            client_name=n,
            report_month=m,
            consultants_count=cc,
            mrr=mr,
        )
        for cid, n, m, cc, mr in rows
    ]


@router.get("/finances", response_model=list[FinanceResponse])
async def list_finances(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    department: Optional[str] = Query(default=None),
    months: int = Query(default=24, ge=1, le=120),
) -> list[FinanceResponse]:
    from_d = date.today() - timedelta(days=months * 30)
    stmt = select(DrFinance).where(DrFinance.report_month >= from_d)
    if department:
        stmt = stmt.where(DrFinance.department == department)
    rows = (
        (await db.execute(stmt.order_by(DrFinance.report_month.desc()))).scalars().all()
    )
    return [
        FinanceResponse(
            report_month=r.report_month,
            total_revenue=r.total_revenue,
            total_costs=r.total_costs,
            profit=(r.total_revenue or Decimal(0)) - (r.total_costs or Decimal(0)),
            cv_database_count=r.cv_database_count,
            consultants_churn=r.consultants_churn,
            department=r.department,
        )
        for r in rows
    ]


@router.get("/summary", response_model=MrrSummary)
async def get_mrr_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    months: int = Query(default=12, ge=1, le=120),
) -> MrrSummary:
    today = date.today()
    from_d = today - timedelta(days=months * 30)
    stmt = select(
        func.coalesce(func.sum(DrClientMrr.mrr), 0),
        func.coalesce(func.avg(DrClientMrr.consultants_count), 0),
        func.count(func.distinct(DrClientMrr.client_id)),
    ).where(
        and_(
            DrClientMrr.report_month >= from_d,
            DrClientMrr.report_month <= today,
        )
    )
    row = (await db.execute(stmt)).first()
    return MrrSummary(
        from_month=from_d,
        to_month=today,
        total_mrr=row[0] or Decimal(0),
        avg_consultants=round(float(row[1] or 0), 2),
        distinct_clients=row[2] or 0,
    )
