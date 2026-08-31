"""Phase 9 B4 — contract margin & utilization analytics.

Endpoints:
- GET /contract-analytics/margin-by-contractor — top N by absolute margin
- GET /contract-analytics/margin-by-client     — per client aggregates
- GET /contract-analytics/utilization          — active vs. bench stats
- GET /contract-analytics/revenue-forecast     — next-12-month projection

All numbers are normalised to monthly equivalents using the rate_unit /
billing_hours_per_month fields introduced in A3.
"""

import logging
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, PlainSerializer

from app.api.financial_access import FinanceReadUser
from app.core.database import get_db
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus, ContractTerminationReason
from app.models.job import Job
from app.services.client_identity import client_display_name_expression
from app.services.fx_service import amount_to_pln_with_rate, get_rate_to_pln
from app.services.contractor_identity import (
    candidate_identity_key,
    contractor_identity_sql_expression,
    unique_contractor_keys,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Money is folded across currencies in Decimal for exactness, but the wire
# format stays a JSON *number* (rounded to grosze). Pydantic serialises a bare
# Decimal as a JSON string here, which the FE (`acc + row.total_monthly_margin`)
# would silently concatenate — so we serialise as float on the way out.
MoneyPLN = Annotated[
    Decimal,
    PlainSerializer(
        lambda v: float(Decimal(v).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)),
        return_type=float,
        when_used="json",
    ),
]


# ── SQL helper: normalise a per-row rate to monthly using rate_unit ───────────

_WORKING_DAYS_PER_MONTH = 22


def _sql_monthly(col):
    return case(
        (Contract.rate_unit == "daily", col * _WORKING_DAYS_PER_MONTH),
        (Contract.rate_unit == "hourly", col * Contract.billing_hours_per_month),
        else_=col,
    )


def _client_currency(contract: Contract) -> str:
    """Currency of revenue, with a rollout-safe fallback for legacy rows."""
    return (contract.rate_client_currency or contract.currency or "PLN").upper()


def _candidate_currency(contract: Contract) -> str:
    """Currency of candidate cost, with a rollout-safe fallback for legacy rows."""
    return (contract.rate_candidate_currency or contract.currency or "PLN").upper()


async def _resolve_rate_cache(db, currencies) -> dict[str, tuple[Decimal, bool]]:
    """Resolve today's PLN multiplier once per distinct currency.

    Returns ``{CURRENCY: (rate, rate_found)}``. Caching per currency avoids an
    FX lookup per aggregate row while keeping the cross-currency conversion.
    """
    cache: dict[str, tuple[Decimal, bool]] = {}
    for currency in currencies:
        cur = (currency or "PLN").upper()
        if cur not in cache:
            cache[cur] = await get_rate_to_pln(db, cur)
    return cache


# ── Pydantic DTOs ─────────────────────────────────────────────────────────────


class MarginByContractor(BaseModel):
    candidate_id: int
    candidate_name: str
    active_contracts: int
    # MoneyPLN, not int: amounts are converted from each contract's currency to
    # PLN before summing, which yields fractional złoty (M7-P0.11).
    total_monthly_margin: MoneyPLN
    total_monthly_revenue: MoneyPLN
    margin_pct: Optional[float]
    # True when at least one contributing currency had no cached FX rate. That
    # leg is excluded; a foreign amount is never treated as PLN at 1:1.
    fx_missing: bool = False


class MarginByClient(BaseModel):
    client_id: int
    client_name: str
    active_contracts: int
    total_monthly_margin: MoneyPLN
    total_monthly_revenue: MoneyPLN
    margin_pct: Optional[float]
    fx_missing: bool = False


class UtilizationStats(BaseModel):
    total_candidates: int
    candidates_active: int
    active_contracts: int
    candidates_on_bench: int
    utilization_pct: float
    avg_bench_days: Optional[float]


class ForecastMonth(BaseModel):
    month: str
    month_label: str
    # MoneyPLN for currency-correct sums (see MarginByContractor note).
    revenue: MoneyPLN
    margin: MoneyPLN
    active_count: int


class RevenueForecast(BaseModel):
    horizon_months: int
    months: List[ForecastMonth]
    # True when any month included a currency with no cached FX rate. Those
    # amounts are EXCLUDED from the totals (not coerced 1:1) — see fx_warnings.
    fx_missing: bool = False
    # Human-readable notes surfacing which currencies were dropped for lack of a
    # cached NBP rate. Empty when every currency converted cleanly.
    fx_warnings: List[str] = []


# ── Endpoints ────────────────────────────────────────────────────────────────


@router.get("/margin-by-contractor", response_model=List[MarginByContractor])
async def margin_by_contractor(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    rev_sql = _sql_monthly(Contract.rate_client).label("revenue")
    cost_sql = _sql_monthly(Contract.rate_candidate).label("cost")
    # Read one row per contract: revenue and candidate cost can now carry two
    # different currencies, so a single SQL ``SUM(margin) GROUP BY currency``
    # has no valid financial meaning. Both legs are converted independently and
    # only then subtracted in PLN.
    res = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Contract.rate_client_currency,
            Contract.rate_candidate_currency,
            Contract.currency,
            rev_sql,
            cost_sql,
        )
        .join(Contract, Contract.candidate_id == Candidate.id)
        .where(Contract.status == ContractStatus.active)
    )
    raw = res.all()
    currencies = {
        currency
        for r in raw
        for currency in (
            (r.rate_client_currency or r.currency or "PLN").upper(),
            (r.rate_candidate_currency or r.currency or "PLN").upper(),
        )
    }
    rate_cache = await _resolve_rate_cache(db, currencies)

    acc: dict[int, dict] = {}
    for r in raw:
        client_currency = (r.rate_client_currency or r.currency or "PLN").upper()
        candidate_currency = (r.rate_candidate_currency or r.currency or "PLN").upper()
        client_fx, client_found = rate_cache[client_currency]
        candidate_fx, candidate_found = rate_cache[candidate_currency]
        bucket = acc.setdefault(
            r.id,
            {
                "name": r.name,
                "lastname": r.lastname,
                "active_contracts": 0,
                "margin": Decimal("0"),
                "revenue": Decimal("0"),
                "fx_missing": False,
            },
        )
        bucket["active_contracts"] += 1
        revenue_pln, revenue_complete = amount_to_pln_with_rate(
            r.revenue, client_fx if client_found else None
        )
        cost_pln, cost_complete = amount_to_pln_with_rate(
            r.cost, candidate_fx if candidate_found else None
        )
        if revenue_pln is not None:
            bucket["revenue"] += revenue_pln
        if revenue_pln is not None and cost_pln is not None:
            bucket["margin"] += revenue_pln - cost_pln
        if not revenue_complete or not cost_complete:
            bucket["fx_missing"] = True

    rows = [
        MarginByContractor(
            candidate_id=cid,
            candidate_name=f"{b['name']} {b['lastname']}",
            active_contracts=b["active_contracts"],
            total_monthly_margin=b["margin"],
            total_monthly_revenue=b["revenue"],
            margin_pct=(
                round(float(b["margin"] / b["revenue"]) * 100, 1)
                if b["revenue"]
                else None
            ),
            fx_missing=b["fx_missing"],
        )
        for cid, b in acc.items()
    ]
    # Rank by PLN-normalised margin (SQL can no longer order/limit — the ranking
    # only makes sense after cross-currency folding).
    rows.sort(key=lambda x: x.total_monthly_margin, reverse=True)
    return rows[:limit]


@router.get("/margin-by-client", response_model=List[MarginByClient])
async def margin_by_client(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(20, ge=1, le=100),
):
    rev_sql = _sql_monthly(Contract.rate_client).label("revenue")
    cost_sql = _sql_monthly(Contract.rate_candidate).label("cost")
    client_name = client_display_name_expression()
    # One row per contract for the same reason as ``margin_by_contractor``:
    # revenue and cost currencies must be resolved independently.
    res = await db.execute(
        select(
            Client.id,
            client_name.label("client_name"),
            Contract.rate_client_currency,
            Contract.rate_candidate_currency,
            Contract.currency,
            rev_sql,
            cost_sql,
        )
        .join(Contract, Contract.client_id == Client.id)
        .where(Contract.status == ContractStatus.active)
    )
    raw = res.all()
    currencies = {
        currency
        for r in raw
        for currency in (
            (r.rate_client_currency or r.currency or "PLN").upper(),
            (r.rate_candidate_currency or r.currency or "PLN").upper(),
        )
    }
    rate_cache = await _resolve_rate_cache(db, currencies)

    acc: dict[int, dict] = {}
    for r in raw:
        client_currency = (r.rate_client_currency or r.currency or "PLN").upper()
        candidate_currency = (r.rate_candidate_currency or r.currency or "PLN").upper()
        client_fx, client_found = rate_cache[client_currency]
        candidate_fx, candidate_found = rate_cache[candidate_currency]
        bucket = acc.setdefault(
            r.id,
            {
                "name": r.client_name,
                "active_contracts": 0,
                "margin": Decimal("0"),
                "revenue": Decimal("0"),
                "fx_missing": False,
            },
        )
        bucket["active_contracts"] += 1
        revenue_pln, revenue_complete = amount_to_pln_with_rate(
            r.revenue, client_fx if client_found else None
        )
        cost_pln, cost_complete = amount_to_pln_with_rate(
            r.cost, candidate_fx if candidate_found else None
        )
        if revenue_pln is not None:
            bucket["revenue"] += revenue_pln
        if revenue_pln is not None and cost_pln is not None:
            bucket["margin"] += revenue_pln - cost_pln
        if not revenue_complete or not cost_complete:
            bucket["fx_missing"] = True

    rows = [
        MarginByClient(
            client_id=cid,
            client_name=b["name"],
            active_contracts=b["active_contracts"],
            total_monthly_margin=b["margin"],
            total_monthly_revenue=b["revenue"],
            margin_pct=(
                round(float(b["margin"] / b["revenue"]) * 100, 1)
                if b["revenue"]
                else None
            ),
            fx_missing=b["fx_missing"],
        )
        for cid, b in acc.items()
    ]
    rows.sort(key=lambda x: x.total_monthly_margin, reverse=True)
    return rows[:limit]


@router.get("/utilization", response_model=UtilizationStats)
async def utilization(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    active_rows = (
        await db.execute(
            select(
                Candidate.id,
                Candidate.name,
                Candidate.lastname,
                Candidate.email,
            )
            .join(Contract, Contract.candidate_id == Candidate.id)
            .where(Contract.status == ContractStatus.active)
        )
    ).all()
    active_keys = unique_contractor_keys(active_rows)
    candidates_active = len(active_keys)
    active_contracts = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar() or 0

    # Count the whole candidate population by the same person identity used by
    # the numerator.  Bench gaps are likewise folded per identity: duplicate
    # profiles contribute only their most recent contract end once.
    today = date.today()
    bench_days_res = await db.execute(
        select(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Candidate.email,
            func.max(Contract.end_date).label("last_end"),
        )
        .outerjoin(Contract, Contract.candidate_id == Candidate.id)
        .group_by(
            Candidate.id,
            Candidate.name,
            Candidate.lastname,
            Candidate.email,
        )
    )
    all_candidate_rows = bench_days_res.all()
    all_keys = unique_contractor_keys(all_candidate_rows)
    total_candidates = len(all_keys)
    bench_keys = all_keys - active_keys
    candidates_on_bench = len(bench_keys)
    bench_last_end: dict[tuple, date] = {}
    for row in all_candidate_rows:
        identity_key = candidate_identity_key(row)
        if identity_key not in bench_keys:
            continue
        last_end = row.last_end
        if last_end is None:
            continue  # candidate never had a contract — skip
        previous = bench_last_end.get(identity_key)
        if previous is None or last_end > previous:
            bench_last_end[identity_key] = last_end

    bench_gaps: list[int] = []
    for last_end in bench_last_end.values():
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
        active_contracts=active_contracts,
        candidates_on_bench=candidates_on_bench,
        utilization_pct=utilization_pct,
        avg_bench_days=avg_bench,
    )


@router.get("/revenue-forecast", response_model=RevenueForecast)
async def revenue_forecast(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    horizon_months: int = Query(12, ge=1, le=24),
    convert_currency: bool = Query(
        True,
        description=(
            "Convert non-PLN amounts to PLN via cached NBP rates (default on). "
            "Pass false only for a deliberately nominal cross-currency sum."
        ),
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

    from app.api.reports import _monthly_rate_candidate, _monthly_rate_client

    # Resolve each leg's currency once (all forecast months use today's rate).
    rate_cache = await _resolve_rate_cache(
        db,
        {
            currency
            for c in active_contracts
            for currency in (_client_currency(c), _candidate_currency(c))
        },
    )
    fx_missing = False
    missing_fx: set[str] = set()

    def _to_display(amount: Decimal | int, currency: str) -> Optional[Decimal]:
        """Convert a monthly amount to PLN, or ``None`` when it must be dropped.

        When ``convert_currency`` is on and a non-PLN currency has no cached NBP
        rate we return ``None`` so the caller EXCLUDES it — coercing 1:1 would
        silently report a foreign amount as if it were PLN (mirrors
        ``analytics.metrics._sum_finance`` / ``reports._fold_finance_pln``).
        ``convert_currency=false`` is the deliberate nominal cross-currency sum,
        so there we keep the raw amount.
        """
        nonlocal fx_missing
        cur = (currency or "PLN").upper()
        if not convert_currency or cur == "PLN":
            return Decimal(amount)
        rate, found = rate_cache.get(cur, (Decimal("1"), False))
        converted, complete = amount_to_pln_with_rate(amount, rate if found else None)
        if not complete:
            fx_missing = True
            missing_fx.add(cur)
            return None
        assert converted is not None
        return converted

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
            # `start_date` is nullable (Contract.start_date: Optional[date]), so
            # comparing it unguarded raised TypeError and answered 500 for the
            # whole forecast as soon as ONE active contract had no start date.
            # Null start = unknown when the revenue begins, so the row is not
            # projected — same convention as `analytics.metrics` builds its
            # month-by-month active series with. A null END date still means
            # open-ended (indefinite contracts) and stays included.
            if c.start_date is not None
            and c.start_date < next_month
            and (c.end_date is None or c.end_date >= month_start)
        ]
        revenue_raw = Decimal("0")
        margin_raw = Decimal("0")
        for c in active_in_month:
            rev = (
                _to_display(_monthly_rate_client(c), _client_currency(c))
                if c.rate_client is not None
                else None
            )
            cost = (
                _to_display(_monthly_rate_candidate(c), _candidate_currency(c))
                if c.rate_candidate is not None
                else None
            )
            if rev is not None:
                revenue_raw += rev
            if rev is not None and cost is not None:
                margin_raw += rev - cost
        months.append(
            ForecastMonth(
                month=month_start.strftime("%Y-%m"),
                month_label=month_start.strftime("%b %Y"),
                revenue=revenue_raw,
                margin=margin_raw,
                active_count=len(active_in_month),
            )
        )

    # Reference to silence unused-arg warning in future linters
    _ = timedelta
    fx_warnings: List[str] = []
    if missing_fx:
        details = ", ".join(sorted(missing_fx))
        fx_warnings.append(
            f"Brak kursu NBP dla walut: {details} — kwoty w tych walutach "
            "POMINIĘTE w prognozie (uzupełnij: POST /api/fx/refresh)"
        )
        logger.warning(
            "contract-analytics/revenue-forecast: missing FX rate(s) for %s — "
            "amounts excluded from forecast totals",
            details,
        )
    return RevenueForecast(
        horizon_months=horizon_months,
        months=months,
        fx_missing=fx_missing,
        fx_warnings=fx_warnings,
    )


# ── Role × Client mix (headcount analytics) ──────────────────────────────────


class RoleClientCell(BaseModel):
    role: str
    client_id: int
    client_name: str
    active_count: int
    pct_of_total: float


class RoleClientMix(BaseModel):
    total_active: int
    # Raw active contract rows, including detached contracts.  The person
    # buckets below intentionally require a Candidate identity and therefore
    # are not a partition of this cross-unit metric.
    total_active_contracts: int
    role_totals: dict[str, int]
    rows: List[RoleClientCell]
    roles: List[str]
    clients: List[dict]  # [{id, name}]


@router.get("/role-client-mix", response_model=RoleClientMix)
async def role_client_mix(
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Count unique active people bucketed by role × client.

    Role is `job.title` when a job is linked; otherwise we fall back to
    `candidate.competence_category`. Contracts without either are grouped
    under `Unknown`. A person may appear in multiple cells, but the global
    person total is deduplicated across the whole active population.
    ``total_active_contracts`` remains a separate raw-contract metric and also
    includes detached rows that cannot appear in a person bucket.
    """
    role_expr = func.coalesce(Job.title, Candidate.competence_category, "Unknown")
    client_name = client_display_name_expression()
    identity_key = contractor_identity_sql_expression(
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.id,
    )
    totals = (
        await db.execute(
            select(
                func.count(distinct(identity_key))
                .filter(Candidate.id.is_not(None))
                .label("contractors"),
                func.count(Contract.id).label("contracts"),
            )
            .select_from(Contract)
            .outerjoin(Candidate, Candidate.id == Contract.candidate_id)
            .where(Contract.status == ContractStatus.active)
        )
    ).one()
    total_active = int(totals.contractors or 0)
    total_active_contracts = int(totals.contracts or 0)
    res = await db.execute(
        select(
            role_expr.label("role"),
            Client.id.label("client_id"),
            client_name.label("client_name"),
            func.count(distinct(identity_key)).label("cnt"),
        )
        .select_from(Contract)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .join(Client, Client.id == Contract.client_id)
        .outerjoin(Job, Job.id == Contract.job_id)
        .where(Contract.status == ContractStatus.active)
        .group_by(role_expr, Client.id, client_name)
        .order_by(func.count(distinct(identity_key)).desc())
    )
    raw = res.all()
    role_totals_res = await db.execute(
        select(
            role_expr.label("role"),
            func.count(distinct(identity_key)).label("cnt"),
        )
        .select_from(Contract)
        .join(Candidate, Candidate.id == Contract.candidate_id)
        .outerjoin(Job, Job.id == Contract.job_id)
        .where(Contract.status == ContractStatus.active)
        .group_by(role_expr)
    )
    role_totals = {row.role: int(row.cnt) for row in role_totals_res.all()}
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
        total_active=total_active,
        total_active_contracts=total_active_contracts,
        role_totals=role_totals,
        rows=rows,
        roles=roles,
        clients=clients,
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
    current_user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
    active_only: bool = Query(
        True, description="If true, only count candidates with an active contract"
    ),
):
    """Bucket unique consultants by hub_city and region.

    When duplicate Candidate profiles share one business identity, the profile
    with the lowest candidate id is the deterministic source of location data.
    """
    base_q = select(
        Candidate.id,
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.hub_city,
        Candidate.region,
    )
    if active_only:
        base_q = base_q.join(Contract, Contract.candidate_id == Candidate.id).where(
            Contract.status == ContractStatus.active
        )
    rows = sorted((await db.execute(base_q.distinct())).all(), key=lambda row: row.id)
    profiles_by_identity = {}
    for row in rows:
        profiles_by_identity.setdefault(candidate_identity_key(row), row)
    selected_profiles = list(profiles_by_identity.values())
    total = len(selected_profiles)
    hub_map: dict[Optional[str], int] = {}
    region_map: dict[Optional[str], int] = {}
    for row in selected_profiles:
        hub = row.hub_city
        region = row.region
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
    current_user: FinanceReadUser,
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
    client_name = client_display_name_expression()
    ended_q = (
        select(Contract, client_name.label("client_name"))
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
