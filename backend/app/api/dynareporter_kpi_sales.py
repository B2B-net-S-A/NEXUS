"""DynaReporter B.2.2 — KPI Sales endpoints (analogiczny do body-leasing)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.dr_kpi_sales import DrKpiSales
from app.models.user import User, UserRole
from app.schemas.dr_kpi_sales import (
    DrKpiSalesCreate,
    DrKpiSalesResponse,
    DrKpiSalesSummary,
)

router = APIRouter()


def _check_admin_or_self(current_user: User, target_user_id: int) -> None:
    is_admin = current_user.role in (
        UserRole.admin, UserRole.delivery_lead, UserRole.head_of_recruitment
    )
    if not is_admin and current_user.id != target_user_id:
        raise HTTPException(status_code=403, detail="Tylko swoje wpisy")


@router.get("/my", response_model=list[DrKpiSalesResponse])
async def list_my_entries(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> list[DrKpiSalesResponse]:
    stmt = select(DrKpiSales).where(DrKpiSales.user_id == current_user.id)
    if from_date:
        stmt = stmt.where(DrKpiSales.report_date >= from_date)
    if to_date:
        stmt = stmt.where(DrKpiSales.report_date <= to_date)
    rows = (await db.execute(stmt.order_by(DrKpiSales.report_date.desc()))).scalars().all()
    return [
        DrKpiSalesResponse.model_validate({
            **r.__dict__, "user_name": current_user.name, "user_email": current_user.email
        })
        for r in rows
    ]


@router.get("/all", response_model=list[DrKpiSalesResponse])
async def list_all_entries(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    from_date: Optional[date] = Query(default=None),
    to_date: Optional[date] = Query(default=None),
) -> list[DrKpiSalesResponse]:
    is_priv = current_user.role in (
        UserRole.admin, UserRole.delivery_lead, UserRole.head_of_recruitment
    )
    stmt = select(DrKpiSales, User.name, User.email).join(User, User.id == DrKpiSales.user_id)
    if user_id:
        if not is_priv and user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Brak dostępu do cudzych")
        stmt = stmt.where(DrKpiSales.user_id == user_id)
    elif not is_priv:
        stmt = stmt.where(DrKpiSales.user_id == current_user.id)
    if from_date:
        stmt = stmt.where(DrKpiSales.report_date >= from_date)
    if to_date:
        stmt = stmt.where(DrKpiSales.report_date <= to_date)
    rows = (await db.execute(stmt.order_by(DrKpiSales.report_date.desc()))).all()
    return [
        DrKpiSalesResponse.model_validate({**r.__dict__, "user_name": n, "user_email": e})
        for r, n, e in rows
    ]


@router.get("/summary", response_model=DrKpiSalesSummary)
async def get_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="month", pattern="^(week|month|quarter|year)$"),
    user_id: Optional[int] = Query(default=None),
) -> DrKpiSalesSummary:
    target_uid = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_uid)

    today = date.today()
    days = {"week": 7, "month": 30, "quarter": 90, "year": 365}[period]
    from_d = today - timedelta(days=days)

    stmt = select(
        func.coalesce(func.sum(DrKpiSales.leads), 0),
        func.coalesce(func.sum(DrKpiSales.offers_sent), 0),
        func.coalesce(func.sum(DrKpiSales.offers_won), 0),
        func.coalesce(func.sum(DrKpiSales.offers_lost), 0),
        func.coalesce(func.sum(DrKpiSales.days_worked), 0),
        func.count(DrKpiSales.id),
    ).where(and_(
        DrKpiSales.user_id == target_uid,
        DrKpiSales.report_date >= from_d,
        DrKpiSales.report_date <= today,
    ))
    row = (await db.execute(stmt)).first()
    won, lost = row[2] or 0, row[3] or 0
    win_rate = won / (won + lost) if (won + lost) > 0 else 0.0
    return DrKpiSalesSummary(
        period=period, from_date=from_d, to_date=today,
        total_leads=row[0] or 0, total_offers_sent=row[1] or 0,
        total_offers_won=won, total_offers_lost=lost,
        total_days_worked=row[4] or 0, entries_count=row[5] or 0,
        win_rate=round(win_rate, 3),
    )


@router.post("", response_model=DrKpiSalesResponse, status_code=status.HTTP_201_CREATED)
async def upsert_entry(
    payload: DrKpiSalesCreate,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
) -> DrKpiSalesResponse:
    target_uid = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_uid)

    stmt = (
        pg_insert(DrKpiSales)
        .values(user_id=target_uid, **payload.model_dump())
        .on_conflict_do_update(
            index_elements=["user_id", "report_date"],
            set_={k: v for k, v in payload.model_dump().items() if k != "report_date"},
        )
        .returning(DrKpiSales)
    )
    row = (await db.execute(stmt)).scalar_one()
    await db.commit()
    tgt = (await db.execute(select(User).where(User.id == target_uid))).scalar_one()
    return DrKpiSalesResponse.model_validate(
        {**row.__dict__, "user_name": tgt.name, "user_email": tgt.email}
    )


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_entry(
    entry_id: int, current_user: CurrentUser, db: AsyncSession = Depends(get_db)
) -> None:
    row = (await db.execute(select(DrKpiSales).where(DrKpiSales.id == entry_id))).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie znaleziony")
    _check_admin_or_self(current_user, row.user_id)
    await db.delete(row)
    await db.commit()
