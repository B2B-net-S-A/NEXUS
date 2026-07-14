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

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel

from app.api.deps import DeliveryLeadPlus
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.models.job import Job
from app.services.fx_service import convert_to_pln, fx_age_days

router = APIRouter()


# ── SQL helper: normalise a per-row rate to monthly using rate_unit ───────────

_WORKING_DAYS_PER_MONTH = 22


def _sql_monthly(col):
    return case(
        (Contract.rate_unit == "daily", col * _WORKING_DAYS_PER_MONTH),
        (Contract.rate_unit == "hourly", col * Contract.billing_hours_per_month),
        else_=col,
    )


async def _to_pln_strict(
    db: AsyncSession, amount: Decimal | int, currency: Optional[str]
) -> Decimal:
    cur = (currency or "PLN").upper()
    if cur != "PLN" and await fx_age_days(db, cur) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing FX rate for {cur}; financial aggregate is unavailable",
        )
    return await convert_to_pln(db, Decimal(amount or 0), cur)


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
    today = date.today()
    rev_sql = _sql_monthly(Contract.rate_client)
    marg_sql = _sql_monthly(Contract.margin)
    res = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Contract.currency,
            func.count(Contract.id).label("active_contracts"),
            func.coalesce(func.sum(marg_sql), 0).label("margin"),
            func.coalesce(func.sum(rev_sql), 0).label("revenue"),
        )
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.start_date.is_not(None),
            Contract.start_date <= today,
            (Contract.end_date.is_(None)) | (Contract.end_date >= today),
        )
        .group_by(Candidate.id, Candidate.name, Candidate.lastname, Contract.currency)
    )
    grouped: dict[int, dict] = {}
    for r in res.all():
        bucket = grouped.setdefault(
            r.id,
            {
                "name": f"{r.name} {r.lastname}",
                "active_contracts": 0,
                "revenue": Decimal("0"),
                "margin": Decimal("0"),
            },
        )
        bucket["active_contracts"] += int(r.active_contracts or 0)
        bucket["revenue"] += await _to_pln_strict(db, r.revenue or 0, r.currency)
        bucket["margin"] += await _to_pln_strict(db, r.margin or 0, r.currency)

    rows = []
    for candidate_id, bucket in sorted(
        grouped.items(), key=lambda item: item[1]["margin"], reverse=True
    )[:limit]:
        revenue = bucket["revenue"]
        margin = bucket["margin"]
        rows.append(
            MarginByContractor(
                candidate_id=candidate_id,
                candidate_name=bucket["name"],
                active_contracts=bucket["active_contracts"],
                total_monthly_margin=int(margin),
                total_monthly_revenue=int(revenue),
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
    today = date.today()
    rev_sql = _sql_monthly(Contract.rate_client)
    marg_sql = _sql_monthly(Contract.margin)
    res = await db.execute(
        select(
            Client.id,
            Client.name,
            Contract.currency,
            func.count(Contract.id).label("active_contracts"),
            func.coalesce(func.sum(marg_sql), 0).label("margin"),
            func.coalesce(func.sum(rev_sql), 0).label("revenue"),
        )
        .join(Contract, Contract.client_id == Client.id)
        .where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.start_date.is_not(None),
            Contract.start_date <= today,
            (Contract.end_date.is_(None)) | (Contract.end_date >= today),
        )
        .group_by(Client.id, Client.name, Contract.currency)
    )
    grouped: dict[int, dict] = {}
    for r in res.all():
        bucket = grouped.setdefault(
            r.id,
            {
                "name": r.name,
                "active_contracts": 0,
                "revenue": Decimal("0"),
                "margin": Decimal("0"),
            },
        )
        bucket["active_contracts"] += int(r.active_contracts or 0)
        bucket["revenue"] += await _to_pln_strict(db, r.revenue or 0, r.currency)
        bucket["margin"] += await _to_pln_strict(db, r.margin or 0, r.currency)

    rows = []
    for client_id, bucket in sorted(
        grouped.items(), key=lambda item: item[1]["margin"], reverse=True
    )[:limit]:
        revenue = bucket["revenue"]
        margin = bucket["margin"]
        rows.append(
            MarginByClient(
                client_id=client_id,
                client_name=bucket["name"],
                active_contracts=bucket["active_contracts"],
                total_monthly_margin=int(margin),
                total_monthly_revenue=int(revenue),
                margin_pct=round((margin / revenue) * 100, 1) if revenue else None,
            )
        )
    return rows


@router.get("/utilization", response_model=UtilizationStats)
async def utilization(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    today = date.today()
    total_candidates = (
        await db.execute(
            select(func.count(func.distinct(Contract.candidate_id))).where(
                Contract.start_date.is_not(None),
                Contract.start_date <= today,
            )
        )
    ).scalar() or 0

    active_res = await db.execute(
        select(func.count(func.distinct(Contract.candidate_id))).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.start_date.is_not(None),
            Contract.start_date <= today,
            (Contract.end_date.is_(None)) | (Contract.end_date >= today),
        )
    )
    candidates_active = active_res.scalar() or 0
    candidates_on_bench = max(0, total_candidates - candidates_active)

    # Avg bench days — count days since each bench candidate's last contract end.
    bench_days_res = await db.execute(
        select(Contract.candidate_id, func.max(Contract.end_date).label("last_end"))
        .where(Contract.start_date.is_not(None), Contract.start_date <= today)
        .group_by(Contract.candidate_id)
    )
    bench_gaps: list[int] = []
    active_candidate_ids_res = await db.execute(
        select(func.distinct(Contract.candidate_id)).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.start_date.is_not(None),
            Contract.start_date <= today,
            (Contract.end_date.is_(None)) | (Contract.end_date >= today),
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
        True,
        description="Deprecated compatibility flag; totals are always converted to PLN.",
    ),
):
    today = date.today()
    first_of_month = today.replace(day=1)

    all_active_res = await db.execute(
        select(Contract).where(
            Contract.status.in_([ContractStatus.active, ContractStatus.ending]),
            Contract.start_date.is_not(None),
        )
    )
    active_contracts = list(all_active_res.scalars().all())

    from app.api.reports import _monthly_margin, _monthly_rate_client

    async def _to_display(amount: int, currency: str) -> int:
        # Financial aggregates must never nominally mix currencies. The legacy
        # query flag is accepted for compatibility but no longer disables FX.
        _ = convert_currency
        converted = await _to_pln_strict(db, Decimal(amount), currency)
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


# ── Role × Client mix (headcount analytics) ──────────────────────────────────


class RoleClientCell(BaseModel):
    role: str
    client_id: int
    client_name: str
    active_count: int
    pct_of_total: float


class RoleClientMix(BaseModel):
    total_active: int
    rows: List[RoleClientCell]
    roles: List[str]
    clients: List[dict]  # [{id, name}]


@router.get("/role-client-mix", response_model=RoleClientMix)
async def role_client_mix(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
):
    """Count active contracts bucketed by role × client.

    Role is `job.title` when a job is linked; otherwise we fall back to
    `candidate.competence_category`. Contracts without either are grouped
    under `Unknown`.
    """
    role_expr = func.coalesce(Job.title, Candidate.competence_category, "Unknown")
    res = await db.execute(
        select(
            role_expr.label("role"),
            Client.id.label("client_id"),
            Client.name.label("client_name"),
            func.count(Contract.id).label("cnt"),
        )
        .select_from(Contract)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .join(Client, Client.id == Contract.client_id)
        .outerjoin(Job, Job.id == Contract.job_id)
        .where(Contract.status == ContractStatus.active)
        .group_by(role_expr, Client.id, Client.name)
        .order_by(func.count(Contract.id).desc())
    )
    raw = res.all()
    total_active = sum(r.cnt for r in raw)
    rows = [
        RoleClientCell(
            role=r.role,
            client_id=r.client_id,
            client_name=r.client_name,
            active_count=int(r.cnt),
            pct_of_total=round((r.cnt / total_active) * 100, 1)
            if total_active
            else 0.0,
        )
        for r in raw
    ]
    roles = sorted({r.role for r in rows})
    clients_seen: dict[int, str] = {}
    for r in rows:
        clients_seen.setdefault(r.client_id, r.client_name)
    clients = [{"id": cid, "name": name} for cid, name in clients_seen.items()]
    return RoleClientMix(
        total_active=total_active, rows=rows, roles=roles, clients=clients
    )


# ── Consultant location distribution ─────────────────────────────────────────


class HubDistribution(BaseModel):
    hub_city: Optional[str]
    count: int


class RegionDistribution(BaseModel):
    region: Optional[str]
    count: int


class LocationDistribution(BaseModel):
    total: int
    total_with_hub: int
    hubs: List[HubDistribution]
    regions: List[RegionDistribution]


@router.get("/location-distribution", response_model=LocationDistribution)
async def location_distribution(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(
        True, description="If true, only count candidates with an active contract"
    ),
):
    """Bucket consultants by hub_city and region for heat-map visualization."""
    base_q = select(Candidate.id, Candidate.hub_city, Candidate.region)
    if active_only:
        base_q = base_q.join(Contract, Contract.candidate_id == Candidate.id).where(
            Contract.status == ContractStatus.active
        )
    rows = (await db.execute(base_q.distinct())).all()
    total = len(rows)
    hub_map: dict[Optional[str], int] = {}
    region_map: dict[Optional[str], int] = {}
    for _, hub, region in rows:
        hub_map[hub] = hub_map.get(hub, 0) + 1
        region_map[region] = region_map.get(region, 0) + 1

    hubs = [
        HubDistribution(hub_city=k, count=v)
        for k, v in sorted(hub_map.items(), key=lambda kv: (kv[0] is None, -kv[1]))
    ]
    regions = [
        RegionDistribution(region=k, count=v)
        for k, v in sorted(region_map.items(), key=lambda kv: (kv[0] is None, -kv[1]))
    ]
    total_with_hub = total - hub_map.get(None, 0)
    return LocationDistribution(
        total=total, total_with_hub=total_with_hub, hubs=hubs, regions=regions
    )


# ── Termination analytics (attrition + retention) ────────────────────────────


class TerminationReasonBucket(BaseModel):
    reason: str
    count: int
    avg_contract_days: Optional[float]


class ClientRetention(BaseModel):
    client_id: int
    client_name: str
    total_ended: int
    kept_to_end: int
    ended_early: int
    retention_pct: float


class TerminationAnalysis(BaseModel):
    window_months: int
    total_terminated: int
    by_reason: List[TerminationReasonBucket]
    client_retention: List[ClientRetention]


@router.get("/termination-analysis", response_model=TerminationAnalysis)
async def termination_analysis(
    current_user: DeliveryLeadPlus,
    db: AsyncSession = Depends(get_db),
    window_months: int = Query(
        12, ge=1, le=36, description="Look-back window in months"
    ),
):
    """Attrition rollup: reasons × clients, with retention percentage."""
    today = date.today()
    window_start_month = today.month - window_months
    window_start_year = today.year
    while window_start_month <= 0:
        window_start_month += 12
        window_start_year -= 1
    window_start = date(window_start_year, window_start_month, 1)

    # All ended contracts in window.
    ended_q = (
        select(Contract, Client.name.label("client_name"))
        .join(Client, Client.id == Contract.client_id)
        .where(
            Contract.status == ContractStatus.ended,
            func.coalesce(Contract.terminated_at, Contract.end_date) >= window_start,
        )
    )
    rows = (await db.execute(ended_q)).all()
    total_terminated = len(rows)

    reason_counts: dict[str, int] = {}
    reason_durations: dict[str, list[int]] = {}
    for contract, _ in rows:
        reason = (
            contract.termination_reason.value
            if contract.termination_reason
            else "unspecified"
        )
        reason_counts[reason] = reason_counts.get(reason, 0) + 1
        duration_end = contract.terminated_at or contract.end_date
        if duration_end and contract.start_date:
            reason_durations.setdefault(reason, []).append(
                (duration_end - contract.start_date).days
            )

    by_reason = [
        TerminationReasonBucket(
            reason=reason,
            count=cnt,
            avg_contract_days=(
                round(sum(reason_durations[reason]) / len(reason_durations[reason]), 1)
                if reason_durations.get(reason)
                else None
            ),
        )
        for reason, cnt in sorted(reason_counts.items(), key=lambda kv: -kv[1])
    ]

    # Client retention: how often does a contract reach its planned end?
    # "Ended early" = terminated_at < end_date OR termination_reason in
    # (poached_by_client, consultant_resigned, better_offer, contract_breach).
    early_reasons = {
        ContractTerminationReason.poached_by_client.value,
        ContractTerminationReason.consultant_resigned.value,
        ContractTerminationReason.better_offer.value,
        ContractTerminationReason.contract_breach.value,
        ContractTerminationReason.performance_issue.value,
    }
    retention_map: dict[int, dict] = {}
    for contract, client_name in rows:
        bucket = retention_map.setdefault(
            contract.client_id,
            {"name": client_name, "total": 0, "kept": 0, "early": 0},
        )
        bucket["total"] += 1
        reason_val = (
            contract.termination_reason.value if contract.termination_reason else None
        )
        is_early = False
        if (
            contract.terminated_at
            and contract.end_date
            and contract.terminated_at < contract.end_date
        ):
            is_early = True
        elif reason_val in early_reasons:
            is_early = True
        if is_early:
            bucket["early"] += 1
        else:
            bucket["kept"] += 1

    retention = [
        ClientRetention(
            client_id=cid,
            client_name=info["name"],
            total_ended=info["total"],
            kept_to_end=info["kept"],
            ended_early=info["early"],
            retention_pct=round((info["kept"] / info["total"]) * 100, 1)
            if info["total"]
            else 0.0,
        )
        for cid, info in sorted(retention_map.items(), key=lambda kv: -kv[1]["total"])
    ]

    return TerminationAnalysis(
        window_months=window_months,
        total_terminated=total_terminated,
        by_reason=by_reason,
        client_retention=retention,
    )
