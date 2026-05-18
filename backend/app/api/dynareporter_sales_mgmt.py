"""DynaReporter B.2.9 — Sales Management endpoints (readonly)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.dr_sales import (
    DrSalesLead,
    DrSalesOffer,
    DrSalesPerson,
    DrSalesProject,
    DrWeeklySalesActivity,
)

router = APIRouter()


class SalesProjectResponse(BaseModel):
    id: int
    name: str
    bdm_id: Optional[int] = None
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SalesPersonResponse(BaseModel):
    id: int
    name: str
    role: str
    is_hod: bool
    is_active: bool
    model_config = ConfigDict(from_attributes=True)


class SalesLeadResponse(BaseModel):
    id: int
    user_id: int
    week_start: date
    company_name: str
    model_config = ConfigDict(from_attributes=True)


class WeeklyActivityResponse(BaseModel):
    week_start: date
    week_number: int
    year: int
    leads_count: int
    offers_sent: int
    model_config = ConfigDict(from_attributes=True)


@router.get("/projects", response_model=list[SalesProjectResponse])
async def list_projects(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    only_active: bool = Query(default=True),
) -> list[SalesProjectResponse]:
    stmt = select(DrSalesProject)
    if only_active:
        stmt = stmt.where(DrSalesProject.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(DrSalesProject.name))).scalars().all()
    return [SalesProjectResponse.model_validate(r.__dict__) for r in rows]


@router.get("/people", response_model=list[SalesPersonResponse])
async def list_people(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    only_active: bool = Query(default=True),
) -> list[SalesPersonResponse]:
    stmt = select(DrSalesPerson)
    if only_active:
        stmt = stmt.where(DrSalesPerson.is_active.is_(True))
    rows = (await db.execute(stmt.order_by(DrSalesPerson.name))).scalars().all()
    return [SalesPersonResponse.model_validate(r.__dict__) for r in rows]


@router.get("/leads", response_model=list[SalesLeadResponse])
async def list_leads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    from_week: Optional[date] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SalesLeadResponse]:
    stmt = select(DrSalesLead)
    if user_id:
        stmt = stmt.where(DrSalesLead.user_id == user_id)
    if from_week:
        stmt = stmt.where(DrSalesLead.week_start >= from_week)
    rows = (await db.execute(stmt.order_by(DrSalesLead.week_start.desc()).limit(limit))).scalars().all()
    return [SalesLeadResponse.model_validate(r.__dict__) for r in rows]


@router.get("/offers", response_model=list[SalesLeadResponse])
async def list_offers(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    from_week: Optional[date] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[SalesLeadResponse]:
    """Offers (same shape as leads — taki sam schema w DR)."""
    stmt = select(DrSalesOffer)
    if user_id:
        stmt = stmt.where(DrSalesOffer.user_id == user_id)
    if from_week:
        stmt = stmt.where(DrSalesOffer.week_start >= from_week)
    rows = (await db.execute(stmt.order_by(DrSalesOffer.week_start.desc()).limit(limit))).scalars().all()
    return [SalesLeadResponse.model_validate(r.__dict__) for r in rows]


@router.get("/weekly-activity", response_model=list[WeeklyActivityResponse])
async def weekly_activity(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    weeks: int = Query(default=12, ge=1, le=52),
) -> list[WeeklyActivityResponse]:
    from_d = date.today() - timedelta(weeks=weeks)
    rows = (
        await db.execute(
            select(DrWeeklySalesActivity)
            .where(DrWeeklySalesActivity.week_start >= from_d)
            .order_by(DrWeeklySalesActivity.week_start.desc())
        )
    ).scalars().all()
    return [WeeklyActivityResponse.model_validate(r.__dict__) for r in rows]
