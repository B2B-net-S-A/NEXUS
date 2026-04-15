"""
DynaMinds ATS — Reporting Module
Generates live reports from ATS data (recruitment, sales, delivery, tenders, board).
"""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.user import User

router = APIRouter()

# ── Helpers ────────────────────────────────────────────────────────────────────

def _period_start(period: str) -> datetime:
    """Return the start datetime for the given period string."""
    now = datetime.now(timezone.utc)
    if period == "week":
        return now - timedelta(days=7)
    elif period == "month":
        return now - timedelta(days=30)
    elif period == "quarter":
        return now - timedelta(days=90)
    elif period == "year":
        return now - timedelta(days=365)
    return datetime.min.replace(tzinfo=timezone.utc)  # all time


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


# ── Recruitment Report ─────────────────────────────────────────────────────────

@router.get("/recruitment")
async def report_recruitment(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
    recruitment_type: Optional[str] = Query(None),
):
    """
    Recruitment funnel report with per-recruiter breakdown and Liga Mistrzów top 3.
    Cached for 5 minutes.
    """
    cache_key = f"reports:recruitment:{period}:{recruitment_type}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    start = _period_start(period)

    # Base subquery: candidate stages joined to jobs (filtered by period & recruitment_type)
    job_filter = []
    if recruitment_type and recruitment_type != "all":
        try:
            rtype = RecruitmentType(recruitment_type)
            job_filter.append(Job.recruitment_type == rtype)
        except ValueError:
            pass

    # We look at the LATEST stage per candidate+job within the period
    # (moved_at >= start means the stage move happened in this period)
    stage_filter = [CandidateStage.moved_at >= start]

    # Global funnel counts (across all recruiters)
    # Weryfikacje = new + screening
    # Rekomendacje = interview
    # Interviews = technical
    # Placements = hired

    async def count_stage(stages: list) -> int:
        q = (
            select(func.count(CandidateStage.id))
            .join(Job, CandidateStage.job_id == Job.id)
            .where(CandidateStage.stage.in_(stages), *stage_filter, *job_filter)
        )
        return (await db.execute(q)).scalar() or 0

    weryfikacje = await count_stage([PipelineStage.new, PipelineStage.screening])
    rekomendacje = await count_stage([PipelineStage.interview])
    interviews = await count_stage([PipelineStage.technical])
    placements = await count_stage([PipelineStage.hired])

    funnel_efficiency = {
        "weryfikacje_to_rekomendacje": _safe_pct(rekomendacje, weryfikacje),
        "rekomendacje_to_interviews": _safe_pct(interviews, rekomendacje),
        "interviews_to_placements": _safe_pct(placements, interviews),
    }

    # Per-recruiter breakdown
    per_recruiter_q = (
        select(
            User.id,
            User.name,
            func.sum(
                case(
                    (CandidateStage.stage.in_([PipelineStage.new, PipelineStage.screening]), 1),
                    else_=0,
                )
            ).label("weryfikacje"),
            func.sum(
                case((CandidateStage.stage == PipelineStage.interview, 1), else_=0)
            ).label("rekomendacje"),
            func.sum(
                case((CandidateStage.stage == PipelineStage.technical, 1), else_=0)
            ).label("interviews"),
            func.sum(
                case((CandidateStage.stage == PipelineStage.hired, 1), else_=0)
            ).label("placements"),
        )
        .join(CandidateStage, User.id == CandidateStage.moved_by)
        .join(Job, CandidateStage.job_id == Job.id)
        .where(CandidateStage.moved_at >= start, *job_filter)
        .group_by(User.id, User.name)
        .order_by(func.sum(case((CandidateStage.stage == PipelineStage.hired, 1), else_=0)).desc())
    )
    rows = (await db.execute(per_recruiter_q)).all()

    per_recruiter = []
    for r in rows:
        w = r.weryfikacje or 0
        p = r.placements or 0
        per_recruiter.append(
            {
                "user_id": r.id,
                "user_name": r.name,
                "weryfikacje": w,
                "rekomendacje": r.rekomendacje or 0,
                "interviews": r.interviews or 0,
                "placements": p,
                "hit_ratio": _safe_pct(p, w),
            }
        )

    # Top 3 — Liga Mistrzów
    top3 = sorted(per_recruiter, key=lambda x: x["placements"], reverse=True)[:3]

    result_data = {
        "period": period,
        "recruitment_type": recruitment_type,
        "funnel": {
            "weryfikacje_count": weryfikacje,
            "rekomendacje_count": rekomendacje,
            "interviews_count": interviews,
            "placements_count": placements,
        },
        "funnel_efficiency": funnel_efficiency,
        "per_recruiter": per_recruiter,
        "top3_liga_mistrzow": top3,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)  # cache 5 min
    return result_data


# ── Sales Report ───────────────────────────────────────────────────────────────

@router.get("/sales")
async def report_sales(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Sales report: revenue, margin, active consultants, MRR trend, top clients.
    Cached for 5 minutes.
    """
    cache_key = "reports:sales"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    today = date.today()

    # Active contracts
    active_q = select(Contract).where(Contract.status == ContractStatus.active)
    active_contracts = (await db.execute(active_q)).scalars().all()

    total_revenue = sum((c.rate_client or 0) * 160 for c in active_contracts)  # ~160h/month
    total_margin = sum((c.margin or 0) * 160 for c in active_contracts)
    active_consultants = len(active_contracts)

    # New contracts this month
    first_of_month = today.replace(day=1)
    new_this_month = (
        await db.execute(
            select(func.count(Contract.id)).where(Contract.created_at >= first_of_month)
        )
    ).scalar() or 0

    # Contracts ending in 30 days
    cutoff = today + timedelta(days=30)
    ending_q = (
        select(Contract, Client.name.label("client_name"))
        .join(Client, Contract.client_id == Client.id)
        .where(
            Contract.end_date.isnot(None),
            Contract.end_date <= cutoff,
            Contract.end_date >= today,
            Contract.status == ContractStatus.active,
        )
    )
    ending_rows = (await db.execute(ending_q)).all()
    ending_contracts_30days = [
        {
            "contract_id": row.Contract.id,
            "client_name": row.client_name,
            "end_date": str(row.Contract.end_date),
            "rate_client": row.Contract.rate_client,
        }
        for row in ending_rows
    ]

    # MRR Trend — last 12 months (from all contracts with start_date in range)
    mrr_trend = []
    for i in range(11, -1, -1):
        month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        # last day of that month
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)

        month_contracts = (
            await db.execute(
                select(Contract).where(
                    Contract.start_date < month_end,
                    (Contract.end_date >= month_start) | Contract.end_date.is_(None),
                    Contract.status.in_([ContractStatus.active, ContractStatus.ending, ContractStatus.ended]),
                )
            )
        ).scalars().all()

        m_revenue = sum((c.rate_client or 0) * 160 for c in month_contracts)
        m_margin = sum((c.margin or 0) * 160 for c in month_contracts)

        mrr_trend.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "month_label": month_start.strftime("%b %Y"),
                "revenue": m_revenue,
                "margin": m_margin,
                "consultants": len(month_contracts),
            }
        )

    # Top clients by revenue
    top_clients_q = (
        select(
            Client.id,
            Client.name,
            func.count(Contract.id).label("contracts_count"),
            func.sum(Contract.rate_client * 160).label("revenue"),
            func.sum(Contract.margin * 160).label("margin"),
        )
        .join(Contract, Client.id == Contract.client_id)
        .where(Contract.status == ContractStatus.active)
        .group_by(Client.id, Client.name)
        .order_by(func.sum(Contract.rate_client * 160).desc())
        .limit(10)
    )
    top_clients_rows = (await db.execute(top_clients_q)).all()
    top_clients = [
        {
            "client_id": r.id,
            "client_name": r.name,
            "contracts_count": r.contracts_count,
            "revenue": int(r.revenue or 0),
            "margin": int(r.margin or 0),
        }
        for r in top_clients_rows
    ]

    result_data = {
        "total_revenue": total_revenue,
        "total_margin": total_margin,
        "active_consultants": active_consultants,
        "new_contracts_this_month": new_this_month,
        "ending_contracts_30days": ending_contracts_30days,
        "mrr_trend": mrr_trend,
        "top_clients": top_clients,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


# ── Delivery Leads Report ──────────────────────────────────────────────────────

@router.get("/delivery-leads")
async def report_delivery_leads(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """
    Delivery Lead performance: requests, vacancies, placements, hit ratio.
    Cached for 5 minutes.
    """
    cache_key = f"reports:delivery_leads:{period}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    start = _period_start(period)

    # Jobs assigned to each recruiter (total_requests)
    jobs_q = (
        select(
            User.id,
            User.name,
            func.count(Job.id).label("total_requests"),
            func.coalesce(func.sum(1), 0).label("total_vacancies"),
        )
        .join(Job, User.id == Job.recruiter_id)
        .where(Job.created_at >= start)
        .group_by(User.id, User.name)
    )
    jobs_rows = (await db.execute(jobs_q)).all()

    # Placements per DL within period
    placements_q = (
        select(
            User.id,
            func.count(CandidateStage.id).label("placements"),
        )
        .join(CandidateStage, User.id == CandidateStage.moved_by)
        .where(
            CandidateStage.stage == PipelineStage.hired,
            CandidateStage.moved_at >= start,
        )
        .group_by(User.id)
    )
    placements_rows = (await db.execute(placements_q)).all()
    placements_map = {r.id: r.placements for r in placements_rows}

    # Clients per DL
    clients_q = (
        select(
            Job.recruiter_id,
            Client.name,
        )
        .join(Client, Job.client_id == Client.id)
        .where(Job.recruiter_id.isnot(None))
        .distinct()
    )
    clients_rows = (await db.execute(clients_q)).all()
    clients_map: dict[int, list[str]] = {}
    for r in clients_rows:
        if r.recruiter_id not in clients_map:
            clients_map[r.recruiter_id] = []
        if r.name not in clients_map[r.recruiter_id]:
            clients_map[r.recruiter_id].append(r.name)

    per_dl = []
    for r in jobs_rows:
        p = placements_map.get(r.id, 0)
        req = r.total_requests or 0
        per_dl.append(
            {
                "user_id": r.id,
                "name": r.name,
                "total_requests": req,
                "total_vacancies": req,  # 1 job = 1 vacancy (simplification)
                "placements": p,
                "hit_ratio": _safe_pct(p, req),
                "clients": clients_map.get(r.id, []),
            }
        )

    # Sort by placements desc
    per_dl.sort(key=lambda x: x["placements"], reverse=True)

    total_req = sum(d["total_requests"] for d in per_dl)
    total_placements = sum(d["placements"] for d in per_dl)
    avg_hit = round(sum(d["hit_ratio"] for d in per_dl) / max(len(per_dl), 1), 1)

    result_data = {
        "period": period,
        "per_dl": per_dl,
        "overall": {
            "total_requests": total_req,
            "total_placements": total_placements,
            "avg_hit_ratio": avg_hit,
        },
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


# ── Tenders Report ─────────────────────────────────────────────────────────────

@router.get("/tenders")
async def report_tenders(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", enum=["week", "month", "quarter", "year"]),
):
    """
    Tenders (przetargi) report: total, won, lost, pending, win rate.
    Cached for 5 minutes.
    """
    cache_key = f"reports:tenders:{period}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    start = _period_start(period)

    tenders_q = (
        select(Job, Client.name.label("client_name"))
        .outerjoin(Client, Job.client_id == Client.id)
        .where(
            Job.recruitment_type == RecruitmentType.tender,
            Job.created_at >= start,
        )
    )
    tenders_rows = (await db.execute(tenders_q)).all()

    total = len(tenders_rows)
    won = sum(1 for r in tenders_rows if r.Job.status.value == "closed" and (r.Job.priority.value in ("high", "urgent")))
    # Simplification: closed + high/urgent = won; closed + low/medium = lost; rest = pending
    # A more robust way: use a dedicated field. For now:
    lost_list = []
    won_list = []
    pending_list = []

    for r in tenders_rows:
        j = r.Job
        value = (j.salary_max or j.salary_min or 0)
        entry = {
            "job_id": j.id,
            "job_title": j.title,
            "client": r.client_name or "—",
            "status": j.status.value,
            "value": value,
            "deadline": str(j.deadline) if j.deadline else None,
        }
        if j.status.value == "closed":
            if j.priority.value in ("high", "urgent"):
                entry["result"] = "wygrana"
                won_list.append(entry)
            else:
                entry["result"] = "przegrana"
                lost_list.append(entry)
        else:
            entry["result"] = "w_toku"
            pending_list.append(entry)

    won_count = len(won_list)
    lost_count = len(lost_list)
    pending_count = len(pending_list)
    win_rate = _safe_pct(won_count, won_count + lost_count)

    per_tender = won_list + lost_list + pending_list

    result_data = {
        "period": period,
        "total_tenders": total,
        "won": won_count,
        "lost": lost_count,
        "pending": pending_count,
        "win_rate": win_rate,
        "per_tender": per_tender,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


# ── Board Report (Rada Nadzorcza) ──────────────────────────────────────────────

@router.get("/board")
async def report_board(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """
    Executive summary for the Supervisory Board (Rada Nadzorcza).
    High-level KPIs + 12-month trends.
    Cached for 5 minutes.
    """
    cache_key = "reports:board"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    today = date.today()
    year_start = today.replace(month=1, day=1)

    # ── Recruitment YTD ──────────────────────────────────────────────────────
    placements_ytd = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage == PipelineStage.hired,
                CandidateStage.moved_at >= year_start,
            )
        )
    ).scalar() or 0

    weryfikacje_ytd = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage.in_([PipelineStage.new, PipelineStage.screening]),
                CandidateStage.moved_at >= year_start,
            )
        )
    ).scalar() or 0
    funnel_eff_avg = _safe_pct(placements_ytd, weryfikacje_ytd)

    # ── Sales YTD ────────────────────────────────────────────────────────────
    active_contracts = (
        await db.execute(select(Contract).where(Contract.status == ContractStatus.active))
    ).scalars().all()

    revenue_ytd = sum((c.rate_client or 0) * 160 for c in active_contracts)
    margin_ytd = sum((c.margin or 0) * 160 for c in active_contracts)
    active_consultants = len(active_contracts)

    # ── Delivery ─────────────────────────────────────────────────────────────
    dl_q = (
        select(
            User.name,
            func.count(CandidateStage.id).label("placements"),
        )
        .join(CandidateStage, User.id == CandidateStage.moved_by)
        .where(
            CandidateStage.stage == PipelineStage.hired,
            CandidateStage.moved_at >= year_start,
        )
        .group_by(User.id, User.name)
        .order_by(func.count(CandidateStage.id).desc())
        .limit(1)
    )
    top_dl_row = (await db.execute(dl_q)).first()
    top_dl = top_dl_row.name if top_dl_row else "—"

    jobs_count = (await db.execute(select(func.count(Job.id)).where(Job.created_at >= year_start))).scalar() or 0
    avg_hit_ratio = _safe_pct(placements_ytd, jobs_count)

    # ── Tenders ──────────────────────────────────────────────────────────────
    tenders_total = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.recruitment_type == RecruitmentType.tender,
                Job.created_at >= year_start,
            )
        )
    ).scalar() or 0
    tenders_won = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.recruitment_type == RecruitmentType.tender,
                Job.status == "closed",
                Job.priority.in_(["high", "urgent"]),
                Job.created_at >= year_start,
            )
        )
    ).scalar() or 0
    tender_win_rate = _safe_pct(tenders_won, tenders_total)

    # ── Headcount ────────────────────────────────────────────────────────────
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_candidates = (await db.execute(select(func.count(Candidate.id)))).scalar() or 0

    # ── 12-month Trends ───────────────────────────────────────────────────────
    trends = []
    for i in range(11, -1, -1):
        month_start = (today.replace(day=1) - timedelta(days=i * 30)).replace(day=1)
        if month_start.month == 12:
            month_end = month_start.replace(year=month_start.year + 1, month=1, day=1)
        else:
            month_end = month_start.replace(month=month_start.month + 1, day=1)

        m_placements = (
            await db.execute(
                select(func.count(CandidateStage.id)).where(
                    CandidateStage.stage == PipelineStage.hired,
                    CandidateStage.moved_at >= month_start,
                    CandidateStage.moved_at < month_end,
                )
            )
        ).scalar() or 0

        m_contracts = (
            await db.execute(
                select(Contract).where(
                    Contract.start_date < month_end,
                    (Contract.end_date >= month_start) | Contract.end_date.is_(None),
                    Contract.status.in_([ContractStatus.active, ContractStatus.ending, ContractStatus.ended]),
                )
            )
        ).scalars().all()

        m_revenue = sum((c.rate_client or 0) * 160 for c in m_contracts)

        trends.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "month_label": month_start.strftime("%b %Y"),
                "placements": m_placements,
                "revenue": m_revenue,
                "consultants": len(m_contracts),
            }
        )

    result_data = {
        "recruitment": {
            "placements_ytd": placements_ytd,
            "funnel_efficiency_avg": funnel_eff_avg,
        },
        "sales": {
            "revenue_ytd": revenue_ytd,
            "margin_ytd": margin_ytd,
            "active_consultants": active_consultants,
        },
        "delivery": {
            "avg_hit_ratio": avg_hit_ratio,
            "top_dl": top_dl,
        },
        "tenders": {
            "total": tenders_total,
            "win_rate": tender_win_rate,
        },
        "headcount": {
            "total_users": total_users,
            "total_candidates": total_candidates,
        },
        "trends": trends,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data
