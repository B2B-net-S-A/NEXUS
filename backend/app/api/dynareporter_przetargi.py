"""DynaReporter B.2.7 — Przetargi endpoints (projects + allocations + costs)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.dr_przetargi import (
    DrPrzetargiAllocation,
    DrPrzetargiConsultant,
    DrPrzetargiProject,
    DrPrzetargiProjectCost,
)

router = APIRouter()


class ProjectResponse(BaseModel):
    id: int
    name: str
    is_active: bool
    client_id: Optional[int] = None


class ConsultantResponse(BaseModel):
    id: int
    name: str
    default_cost_rate: Decimal
    default_revenue_rate: Decimal
    is_active: bool


class AllocationRow(BaseModel):
    id: int
    project_id: int
    project_name: Optional[str] = None
    consultant_id: int
    consultant_name: Optional[str] = None
    month: date
    hours: Decimal
    cost_rate: Decimal
    revenue_rate: Decimal
    revenue: Decimal  # hours * revenue_rate
    cost: Decimal  # hours * cost_rate
    margin: Decimal  # revenue - cost


class ProjectSummary(BaseModel):
    project_id: int
    project_name: str
    months_count: int
    total_hours: Decimal
    total_revenue: Decimal
    total_cost: Decimal
    other_costs: Decimal = Field(
        description="Suma kosztów non-consultant z costs table"
    )
    net_value: Decimal = Field(description="revenue - cost - other_costs")
    margin_pct: float = Field(description="net_value / revenue × 100")


@router.get("/projects", response_model=list[ProjectResponse])
async def list_projects(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    only_active: bool = Query(default=True),
) -> list[ProjectResponse]:
    stmt = select(DrPrzetargiProject)
    if only_active:
        stmt = stmt.where(DrPrzetargiProject.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(DrPrzetargiProject.name))).scalars().all()
    return [ProjectResponse.model_validate(r.__dict__) for r in rows]


@router.get("/consultants", response_model=list[ConsultantResponse])
async def list_consultants(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    only_active: bool = Query(default=True),
) -> list[ConsultantResponse]:
    stmt = select(DrPrzetargiConsultant)
    if only_active:
        stmt = stmt.where(DrPrzetargiConsultant.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(DrPrzetargiConsultant.name))).scalars().all()
    return [ConsultantResponse.model_validate(r.__dict__) for r in rows]


@router.get("/allocations", response_model=list[AllocationRow])
async def list_allocations(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    project_id: Optional[int] = Query(default=None),
    consultant_id: Optional[int] = Query(default=None),
    from_month: Optional[date] = Query(default=None),
    to_month: Optional[date] = Query(default=None),
) -> list[AllocationRow]:
    stmt = (
        select(
            DrPrzetargiAllocation,
            DrPrzetargiProject.name,
            DrPrzetargiConsultant.name,
        )
        .outerjoin(
            DrPrzetargiProject,
            DrPrzetargiProject.id == DrPrzetargiAllocation.project_id,
        )
        .outerjoin(
            DrPrzetargiConsultant,
            DrPrzetargiConsultant.id == DrPrzetargiAllocation.consultant_id,
        )
    )
    if project_id:
        stmt = stmt.where(DrPrzetargiAllocation.project_id == project_id)
    if consultant_id:
        stmt = stmt.where(DrPrzetargiAllocation.consultant_id == consultant_id)
    if from_month:
        stmt = stmt.where(DrPrzetargiAllocation.month >= from_month)
    if to_month:
        stmt = stmt.where(DrPrzetargiAllocation.month <= to_month)
    rows = (await db.execute(stmt.order_by(DrPrzetargiAllocation.month.desc()))).all()
    out = []
    for r, p_name, c_name in rows:
        revenue = (r.hours or Decimal(0)) * (r.revenue_rate or Decimal(0))
        cost = (r.hours or Decimal(0)) * (r.cost_rate or Decimal(0))
        out.append(
            AllocationRow(
                id=r.id,
                project_id=r.project_id,
                project_name=p_name,
                consultant_id=r.consultant_id,
                consultant_name=c_name,
                month=r.month,
                hours=r.hours or Decimal(0),
                cost_rate=r.cost_rate or Decimal(0),
                revenue_rate=r.revenue_rate or Decimal(0),
                revenue=revenue,
                cost=cost,
                margin=revenue - cost,
            )
        )
    return out


@router.get("/project-summary", response_model=list[ProjectSummary])
async def project_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_month: Optional[date] = Query(default=None),
    to_month: Optional[date] = Query(default=None),
) -> list[ProjectSummary]:
    """Per project aggregate: revenue, cost, other_costs, margin."""
    # Allocations sum per project
    alloc_stmt = select(
        DrPrzetargiAllocation.project_id,
        func.count(func.distinct(DrPrzetargiAllocation.month)),
        func.coalesce(func.sum(DrPrzetargiAllocation.hours), 0),
        func.coalesce(
            func.sum(DrPrzetargiAllocation.hours * DrPrzetargiAllocation.revenue_rate),
            0,
        ),
        func.coalesce(
            func.sum(DrPrzetargiAllocation.hours * DrPrzetargiAllocation.cost_rate), 0
        ),
    )
    if from_month:
        alloc_stmt = alloc_stmt.where(DrPrzetargiAllocation.month >= from_month)
    if to_month:
        alloc_stmt = alloc_stmt.where(DrPrzetargiAllocation.month <= to_month)
    alloc_stmt = alloc_stmt.group_by(DrPrzetargiAllocation.project_id)
    alloc_rows = {
        pid: (mc, h, r, c) for pid, mc, h, r, c in (await db.execute(alloc_stmt)).all()
    }

    # Other costs sum per project
    cost_stmt = select(
        DrPrzetargiProjectCost.project_id,
        func.coalesce(func.sum(DrPrzetargiProjectCost.value), 0),
    )
    if from_month:
        cost_stmt = cost_stmt.where(DrPrzetargiProjectCost.month >= from_month)
    if to_month:
        cost_stmt = cost_stmt.where(DrPrzetargiProjectCost.month <= to_month)
    cost_stmt = cost_stmt.group_by(DrPrzetargiProjectCost.project_id)
    cost_rows = {pid: c for pid, c in (await db.execute(cost_stmt)).all()}

    # Project names
    projects = {
        p.id: p.name
        for p in (await db.execute(select(DrPrzetargiProject))).scalars().all()
    }

    out: list[ProjectSummary] = []
    for pid, (months, hours, revenue, cost) in alloc_rows.items():
        other = cost_rows.get(pid, Decimal(0))
        net = (revenue or Decimal(0)) - (cost or Decimal(0)) - (other or Decimal(0))
        rev_d = revenue or Decimal(0)
        margin_pct = float(net) / float(rev_d) * 100 if rev_d > 0 else 0.0
        out.append(
            ProjectSummary(
                project_id=pid,
                project_name=projects.get(pid, f"#{pid}"),
                months_count=months or 0,
                total_hours=hours or Decimal(0),
                total_revenue=rev_d,
                total_cost=cost or Decimal(0),
                other_costs=other or Decimal(0),
                net_value=net,
                margin_pct=round(margin_pct, 2),
            )
        )
    out.sort(key=lambda x: x.net_value, reverse=True)
    return out
