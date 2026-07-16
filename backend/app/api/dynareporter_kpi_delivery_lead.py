"""DynaReporter B.2.3 — KPI Delivery Lead endpoints (miesięczne)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AdminUser, CurrentUser, RecruiterPlus
from app.core.database import get_db
from app.models.dr_kpi_delivery_lead import DrKpiDeliveryLead
from app.models.user import User, UserRole
from app.schemas.dr_kpi_delivery_lead import (
    DrKpiDeliveryLeadCreate,
    DrKpiDeliveryLeadResponse,
    DrKpiDeliveryLeadSummary,
)

router = APIRouter()


def _check_admin_or_self(current_user: User, target_user_id: int) -> None:
    is_admin = current_user.role in (
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    if not is_admin and current_user.id != target_user_id:
        raise HTTPException(status_code=403, detail="Tylko swoje wpisy")


@router.get("/my", response_model=list[DrKpiDeliveryLeadResponse])
async def list_my(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    from_month: Optional[date] = Query(default=None),
    to_month: Optional[date] = Query(default=None),
) -> list[DrKpiDeliveryLeadResponse]:
    stmt = select(DrKpiDeliveryLead).where(DrKpiDeliveryLead.user_id == current_user.id)
    if from_month:
        stmt = stmt.where(DrKpiDeliveryLead.report_month >= from_month)
    if to_month:
        stmt = stmt.where(DrKpiDeliveryLead.report_month <= to_month)
    rows = (
        (await db.execute(stmt.order_by(DrKpiDeliveryLead.report_month.desc())))
        .scalars()
        .all()
    )
    return [
        DrKpiDeliveryLeadResponse.model_validate(
            {
                **r.__dict__,
                "user_name": current_user.name,
                "user_email": current_user.email,
            }
        )
        for r in rows
    ]


@router.get("/all", response_model=list[DrKpiDeliveryLeadResponse])
async def list_all(
    current_user: RecruiterPlus,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    from_month: Optional[date] = Query(default=None),
    to_month: Optional[date] = Query(default=None),
) -> list[DrKpiDeliveryLeadResponse]:
    is_priv = current_user.role in (
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
    )
    stmt = select(DrKpiDeliveryLead, User.name, User.email).join(
        User, User.id == DrKpiDeliveryLead.user_id
    )
    if user_id:
        if not is_priv and user_id != current_user.id:
            raise HTTPException(status_code=403, detail="Brak dostępu")
        stmt = stmt.where(DrKpiDeliveryLead.user_id == user_id)
    elif not is_priv:
        stmt = stmt.where(DrKpiDeliveryLead.user_id == current_user.id)
    if from_month:
        stmt = stmt.where(DrKpiDeliveryLead.report_month >= from_month)
    if to_month:
        stmt = stmt.where(DrKpiDeliveryLead.report_month <= to_month)
    rows = (
        await db.execute(stmt.order_by(DrKpiDeliveryLead.report_month.desc()))
    ).all()
    return [
        DrKpiDeliveryLeadResponse.model_validate(
            {**r.__dict__, "user_name": n, "user_email": e}
        )
        for r, n, e in rows
    ]


@router.get("/summary", response_model=DrKpiDeliveryLeadSummary)
async def get_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
    months: int = Query(default=12, ge=1, le=120),
) -> DrKpiDeliveryLeadSummary:
    target_uid = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_uid)
    from_d = date.today() - timedelta(days=months * 30)

    stmt = select(
        func.count(DrKpiDeliveryLead.id),
        func.coalesce(func.sum(DrKpiDeliveryLead.requests), 0),
        func.coalesce(func.sum(DrKpiDeliveryLead.placements), 0),
        func.coalesce(func.sum(DrKpiDeliveryLead.vacancies), 0),
        func.coalesce(func.avg(DrKpiDeliveryLead.open_requests), 0),
        func.coalesce(func.avg(DrKpiDeliveryLead.open_vacancies), 0),
    ).where(
        and_(
            DrKpiDeliveryLead.user_id == target_uid,
            DrKpiDeliveryLead.report_month >= from_d,
        )
    )
    row = (await db.execute(stmt)).first()
    cnt, req, plc, vac, avg_or, avg_ov = row
    fill = (plc / req) if req and req > 0 else 0.0
    return DrKpiDeliveryLeadSummary(
        months_count=cnt or 0,
        total_requests=req or 0,
        total_placements=plc or 0,
        total_vacancies=vac or 0,
        avg_open_requests=round(float(avg_or or 0), 2),
        avg_open_vacancies=round(float(avg_ov or 0), 2),
        fill_rate=round(fill, 3),
    )


@router.post(
    "", response_model=DrKpiDeliveryLeadResponse, status_code=status.HTTP_201_CREATED
)
async def upsert(
    payload: DrKpiDeliveryLeadCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(default=None),
) -> DrKpiDeliveryLeadResponse:
    target_uid = user_id if user_id is not None else current_user.id
    _check_admin_or_self(current_user, target_uid)

    set_dict = {k: v for k, v in payload.model_dump().items() if k != "report_month"}
    stmt = (
        pg_insert(DrKpiDeliveryLead)
        .values(user_id=target_uid, **payload.model_dump())
        .on_conflict_do_update(
            index_elements=["user_id", "report_month"], set_=set_dict
        )
        .returning(DrKpiDeliveryLead)
    )
    row = (await db.execute(stmt)).scalar_one()
    await db.commit()
    tgt = (await db.execute(select(User).where(User.id == target_uid))).scalar_one()
    return DrKpiDeliveryLeadResponse.model_validate(
        {**row.__dict__, "user_name": tgt.name, "user_email": tgt.email}
    )


@router.delete(
    "/{entry_id}", status_code=status.HTTP_204_NO_CONTENT, response_model=None
)
async def delete_entry(
    entry_id: int, current_user: AdminUser, db: AsyncSession = Depends(get_db)
) -> None:
    row = (
        await db.execute(
            select(DrKpiDeliveryLead).where(DrKpiDeliveryLead.id == entry_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Wpis nie znaleziony")
    _check_admin_or_self(current_user, row.user_id)
    await db.delete(row)
    await db.commit()
