"""Phase 9 B4 — contract margin & utilization analytics.

Endpoints:
- GET /contract-analytics/margin-by-contractor — top N by absolute margin
- GET /contract-analytics/margin-by-client     — per client aggregates
- GET /contract-analytics/utilization          — active vs. bench stats
- GET /contract-analytics/revenue-forecast     — next-12-month projection

All numbers are normalised to monthly equivalents using the rate_unit /
billing_hours_per_month fields introduced in A3.
"""

from datetime import date, timedelta
from decimal import Decimal
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.deps import DeliveryLeadPlus
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.services.fx_service import convert_to_pln

router = APIRouter()


# ── SQL helper: normalise a per-row rate to monthly using rate_unit ───────────

_WORKING_DAYS_PER_MONTH = 22


def _sql_monthly(col):
    return case(
        (Contract.rate_unit == "daily", col * _WORKING_DAYS_PER_MONTH),
        (Contract.rate_unit == "hourly", col * Contract.billing_hours_per_month),
        else_=col,
    )


# ── Pydantic DTOs ─────────────────────────────────────────────────────────────


class MarginByContractor(BaseModel):
    candidate_id: int
    candidate_name: str
    active_contracts: int
    total_monthly_margin: int
    total_monthly_revenue: int
    margin_pct: Optional[float]


class MarginByClient(BaseModel):
    client_id: int
    client_name: str
    active_contracts: int
    total_monthly_margin: int
    total_monthly_revenue: int
    margin_pct: Optional[float]


class UtilizationStats(BaseModel):
    total_candidates: int
    candidates_active: int
    candidates_on_bench: int
    utilization_pct: float
    avg_bench_days: Optional[float]


class ForecastMonth(BaseModel):
    month: str
    month_label: str
    revenue: int
    margin: int
    active_count: int


class RevenueForecast(BaseModel):
    horizon_months: int
    months: List[ForecastMonth]


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/margin-by-contractor", response_model=List[MarginByContractor])
async def margin_by_contractor(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    rev_sql = _sql_monthly(Contract.rate_client)
    marg_sql = _sql_monthly(Contract.margin)
    res = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            func.count(Contract.id).label("active_contracts"),
            func.coalesce(func.sum(marg_sql), 0).label("margin"),
            func.coalesce(func.sum(rev_sql), 0).label("revenue"),
        )
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.status == ContractStatus.active)
        .group_by(Candidate.id, Candidate.name, Candidate.lastname)
        .order_by(func.sum(marg_sql).desc())
        .limit(limit)
    )
    rows = []
    for r in res.all():
        revenue = int(r.revenue or 0)
        margin = int(r.margin or 0)
        rows.append(
            MarginByContractor(
                candidate_id=r.id,
                candidate_name=f"{r.name} {r.lastname}",
                active_contracts=r.active_contracts,
                total_monthly_margin=margin,
                total_monthly_revenue=revenue,
                margin_pct=round((margin / revenue) * 100, 1) if revenue else None,
            )
        )
    return rows


@router.get("/margin-by-client", response_model=List[MarginByClient])
async def margin_by_client(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    rev_sql = _sql_monthly(Contract.rate_client)
    marg_sql = _sql_monthly(Contract.margin)
    res = await db.execute(
        select(
            Client.id,
            Client.name,
            func.count(Contract.id).label("active_contracts"),
            func.coalesce(func.sum(marg_sql), 0).label("margin"),
            func.coalesce(func.sum(rev_sql), 0).label("revenue"),
        )
        .join(Contract, Contract.client_id == Client.id)
        .where(Contract.status == ContractStatus.active)
        .group_by(Client.id, Client.name)
        .order_by(func.sum(marg_sql).desc())
        .limit(limit)
    )
    rows = []
    for r in res.all():
        revenue = int(r.revenue or 0)
        margin = int(r.margin or 0)
        rows.append(
            MarginByClient(
                client_id=r.id,
                client_name=r.name,
                active_contracts=r.active_contracts,
                total_monthly_margin=margin,
                total_monthly_revenue=revenue,
                margin_pct=round((margin / revenue) * 100, 1) if revenue else None,
            )
        )
    return rows


@router.get("/utilization", response_model=UtilizationStats)
async def utilization(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    total_candidates = (
        await db.execute(select(func.count(Candidate.id)))
    ).scalar() or 0

    active_res = await db.execute(
        select(func.count(func.distinct(Contract.candidate_id))).where(
            Contract.status == ContractStatus.active
        )
    )
    candidates_active = active_res.scalar() or 0
    candidates_on_bench = max(0, total_candidates - candidates_active)

    # Avg bench days — count days since each bench candidate's last contract end.
    today = date.today()
    bench_days_res = await db.execute(
        select(Candidate.id, func.max(Contract.end_date).label("last_end"))
        .outerjoin(Contract, Contract.candidate_id == Candidate.id)
        .group_by(Candidate.id)
    )
    bench_gaps: list[int] = []
    active_candidate_ids_res = await db.execute(
        select(func.distinct(Contract.candidate_id)).where(
            Contract.status == ContractStatus.active
        )
    )
    active_ids = {row[0] for row in active_candidate_ids_res.all() if row[0]}
    for cid, last_end in bench_days_res.all():
        if cid in active_ids:
            continue
        if last_end is None:
            continue  # candidate never had a contract — skip
        gap = (today - last_end).days
        if gap > 0:
            bench_gaps.append(gap)
    avg_bench = round(sum(bench_gaps) / len(bench_gaps), 1) if bench_gaps else None

    utilization_pct = (
        round((candidates_active / total_candidates) * 100, 1)
        if total_candidates
        else 0.0
    )
    return UtilizationStats(
        total_candidates=total_candidates,
        candidates_active=candidates_active,
        candidates_on_bench=candidates_on_bench,
        utilization_pct=utilization_pct,
        avg_bench_days=avg_bench,
    )


@router.get("/revenue-forecast", response_model=RevenueForecast)
async def revenue_forecast(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    horizon_months: int = Query(12, ge=1, le=24),
    convert_currency: bool = Query(
        False,
        description="If true, converts non-PLN amounts to PLN via cached NBP rates.",
    ),
):
    today = date.today()
    first_of_month = today.replace(day=1)

    all_active_res = await db.execute(
        select(Contract).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending])
        )
    )
    active_contracts = list(all_active_res.scalars().all())

    from app.api.reports import _monthly_margin, _monthly_rate_client

    async def _to_display(amount: int, currency: str) -> int:
        if not convert_currency or (currency or "PLN").upper() == "PLN":
            return amount
        converted = await convert_to_pln(db, Decimal(amount), currency)
        return int(converted)

    months: list[ForecastMonth] = []
    for i in range(horizon_months):
        month = first_of_month.month + i
        year = first_of_month.year + (month - 1) // 12
        month = ((month - 1) % 12) + 1
        month_start = first_of_month.replace(year=year, month=month, day=1)
        if month == 12:
            next_month = month_start.replace(year=year + 1, month=1, day=1)
        else:
            next_month = month_start.replace(month=month + 1, day=1)

        active_in_month = [
            c
            for c in active_contracts
            if c.start_date < next_month
            and (c.end_date is None or c.end_date >= month_start)
        ]
        revenue_raw = 0
        margin_raw = 0
        for c in active_in_month:
            revenue_raw += await _to_display(_monthly_rate_client(c), c.currency)
            margin_raw += await _to_display(_monthly_margin(c), c.currency)
        months.append(
            ForecastMonth(
                month=month_start.strftime("%Y-%m"),
                month_label=month_start.strftime("%b %Y"),
                revenue=int(revenue_raw),
                margin=int(margin_raw),
                active_count=len(active_in_month),
            )
        )

    # Reference to silence unused-arg warning in future linters
    _ = timedelta
    return RevenueForecast(horizon_months=horizon_months, months=months)
