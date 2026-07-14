"""DynaReporter B.2.8 — Board Monthly Report endpoints (readonly)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    DynaReporterSection,
    require_dynareporter_section,
)
from app.core.database import get_db
from app.models.dr_board import DrBoardMonthlyReport, DrBoardPlacementClient

router = APIRouter(
    dependencies=[Depends(require_dynareporter_section(DynaReporterSection.board))]
)


class BoardMonthlyResponse(BaseModel):
    report_month: date
    revenue: Decimal
    consultant_costs: Decimal
    other_costs: Decimal
    profit: Decimal
    active_consultants: int
    departures: int
    placements: int
    avg_margin_per_hour: Decimal
    hit_ratio: Decimal
    placements_by_client: list[dict] = []


@router.get("/months", response_model=list[BoardMonthlyResponse])
async def list_months(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    months: int = Query(default=12, ge=1, le=120),
) -> list[BoardMonthlyResponse]:
    from_d = date.today() - timedelta(days=months * 31)
    stmt = (
        select(DrBoardMonthlyReport)
        .where(DrBoardMonthlyReport.report_month >= from_d)
        .order_by(DrBoardMonthlyReport.report_month.desc())
    )
    reports = (await db.execute(stmt)).scalars().all()

    # Batch fetch placements_by_client dla wszystkich miesięcy
    months_list = [r.report_month for r in reports]
    pbc_stmt = select(DrBoardPlacementClient).where(
        DrBoardPlacementClient.report_month.in_(months_list)
    )
    pbc_rows = (await db.execute(pbc_stmt)).scalars().all()
    pbc_map: dict[date, list[dict]] = {}
    for p in pbc_rows:
        pbc_map.setdefault(p.report_month, []).append(
            {"client_name": p.client_name, "placement_count": p.placement_count}
        )

    out: list[BoardMonthlyResponse] = []
    for r in reports:
        profit = (
            (r.revenue or Decimal(0))
            - (r.consultant_costs or Decimal(0))
            - (r.other_costs or Decimal(0))
        )
        out.append(
            BoardMonthlyResponse(
                report_month=r.report_month,
                revenue=r.revenue or Decimal(0),
                consultant_costs=r.consultant_costs or Decimal(0),
                other_costs=r.other_costs or Decimal(0),
                profit=profit,
                active_consultants=r.active_consultants or 0,
                departures=r.departures or 0,
                placements=r.placements or 0,
                avg_margin_per_hour=r.avg_margin_per_hour or Decimal(0),
                hit_ratio=r.hit_ratio or Decimal(0),
                placements_by_client=pbc_map.get(r.report_month, []),
            )
        )
    return out


@router.get("/latest", response_model=Optional[BoardMonthlyResponse])
async def latest_month(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> Optional[BoardMonthlyResponse]:
    stmt = (
        select(DrBoardMonthlyReport)
        .order_by(DrBoardMonthlyReport.report_month.desc())
        .limit(1)
    )
    r = (await db.execute(stmt)).scalar_one_or_none()
    if r is None:
        return None
    pbc = (
        (
            await db.execute(
                select(DrBoardPlacementClient).where(
                    DrBoardPlacementClient.report_month == r.report_month
                )
            )
        )
        .scalars()
        .all()
    )
    profit = (
        (r.revenue or Decimal(0))
        - (r.consultant_costs or Decimal(0))
        - (r.other_costs or Decimal(0))
    )
    return BoardMonthlyResponse(
        report_month=r.report_month,
        revenue=r.revenue or Decimal(0),
        consultant_costs=r.consultant_costs or Decimal(0),
        other_costs=r.other_costs or Decimal(0),
        profit=profit,
        active_consultants=r.active_consultants or 0,
        departures=r.departures or 0,
        placements=r.placements or 0,
        avg_margin_per_hour=r.avg_margin_per_hour or Decimal(0),
        hit_ratio=r.hit_ratio or Decimal(0),
        placements_by_client=[
            {"client_name": p.client_name, "placement_count": p.placement_count}
            for p in pbc
        ],
    )
