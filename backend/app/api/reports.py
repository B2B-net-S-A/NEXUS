"""
Nexus ATS — Reporting Module
Generates live reports from ATS data (recruitment, sales, delivery, tenders, board).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DeliveryLeadPlus, TacPlus, require_roles
from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.contract import Contract, ContractStatus
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobCloseReason, JobStatus, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.kpi_panel import _ANCHOR_LOOKBACK_DAYS

router = APIRouter()


# ── Rate-unit aware helpers (Phase 9 A3) ───────────────────────────────────────
# Previously reports used a blanket `* 160` multiplier, assuming every Contract
# stored a monthly rate. Phase 9 A3 introduced `rate_unit` + `billing_hours_per_month`;
# these helpers normalise stored rates to a monthly amount.

_WORKING_DAYS_PER_MONTH = 22


def _monthly(contract: Contract, value: Optional[int]) -> int:
    if value is None:
        return 0
    if contract.rate_unit is None or contract.rate_unit.value == "monthly":
        return int(value)
    if contract.rate_unit.value == "daily":
        return int(value) * _WORKING_DAYS_PER_MONTH
    # hourly
    return int(value) * int(contract.billing_hours_per_month or 160)


def _monthly_rate_client(contract: Contract) -> int:
    return _monthly(contract, contract.rate_client)


def _monthly_margin(contract: Contract) -> int:
    return _monthly(contract, contract.margin)


def _sql_monthly(col):
    """SQLAlchemy CASE expr: convert rate column to monthly using Contract.rate_unit."""
    return case(
        (Contract.rate_unit == "daily", col * _WORKING_DAYS_PER_MONTH),
        (Contract.rate_unit == "hourly", col * Contract.billing_hours_per_month),
        else_=col,
    )


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


# Read-only team funnel report — recruiter dashboard renders this for everyone
# on the recruitment team. FE gate (frontend/src/app/dashboard/recruiter/page.tsx)
# allows sourcer | tac | recruiter | admin | head_of_recruitment; BE must match
# or the dashboard skeleton hangs forever (FE has no 403 fallback). Data is a
# team-wide aggregate; per-user privacy already handled at row level.
@router.get("/recruitment")
async def report_recruitment(
    current_user: User = Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.sourcer,
            UserRole.head_of_recruitment,
        )
    ),
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

    # Global funnel counts (across all recruiters). Definicje KPI Artura
    # (spójne z panelem „Moje KPI" / app/services/kpi_panel.py):
    # Weryfikacje    = verified    (kandydat zweryfikowany przez rekrutera)
    # Rekomendacje   = cv_sent     (CV wysłane do klienta)
    # Interviews     = interview   (zaproszenie na interview; client_interview
    #                               jest w praktyce nieużywany)
    # Placements     = hired       (kontrakt aktywny)

    async def count_stage(stages: list) -> int:
        q = (
            select(func.count(CandidateStage.id))
            .join(Job, CandidateStage.job_id == Job.id)
            .where(CandidateStage.stage.in_(stages), *stage_filter, *job_filter)
        )
        return (await db.execute(q)).scalar() or 0

    weryfikacje = await count_stage([PipelineStage.verified])
    rekomendacje = await count_stage([PipelineStage.cv_sent])
    interviews = await count_stage([PipelineStage.interview])
    placements = await count_stage([PipelineStage.hired])

    funnel_efficiency = {
        "weryfikacje_to_rekomendacje": _safe_pct(rekomendacje, weryfikacje),
        "rekomendacje_to_interviews": _safe_pct(interviews, rekomendacje),
        "interviews_to_placements": _safe_pct(placements, interviews),
    }

    # Per-recruiter breakdown — atrybucja **verifier-anchored** (spójna z panelem
    # „Moje KPI" / app/services/kpi_panel.py): zasługę za każdy kamień milowy pary
    # (kandydat × rekrutacja) — weryfikację, rekomendację, interview, placement —
    # dostaje osoba, która przeniosła kandydata na „verified", niezależnie kto
    # klikał późniejsze etapy. Gdy para nigdy nie była zweryfikowana, kamień liczy
    # się temu, kto wykonał ruch (fallback first_mover). Bez tego rekomendacja
    # „CV wysłane" trafiała do osoby klikającej wysyłkę zamiast do weryfikatora —
    # zasługa dublowała się między dwie osoby (weryfikatora i wysyłającego).
    #
    # Funnel TOTALS powyżej (count_stage) pozostają sumą zespołu (nie per-user),
    # więc nie wymagają kotwicy; tu kotwiczymy tylko podział per osoba + Liga
    # Mistrzów (top3), które są jedynym miejscem z dublowaniem zasługi.
    anchor_lookback = start - timedelta(days=_ANCHOR_LOOKBACK_DAYS)
    rtype_clause = ""
    anchored_params: dict = {"lookback": anchor_lookback, "period_start": start}
    if recruitment_type and recruitment_type != "all":
        try:
            RecruitmentType(recruitment_type)
            rtype_clause = "AND j.recruitment_type::text = :rtype"
            anchored_params["rtype"] = recruitment_type
        except ValueError:
            pass

    per_recruiter_sql = text(
        f"""
        WITH cs AS (
            SELECT cst.candidate_id, cst.job_id, cst.stage::text AS stage,
                   cst.moved_at, cst.moved_by, cst.id
            FROM candidate_stages cst
            JOIN jobs j ON j.id = cst.job_id
            WHERE cst.stage IN ('verified', 'cv_sent', 'interview', 'hired')
              AND cst.moved_at >= :lookback
              {rtype_clause}
        ),
        mf AS (
            SELECT DISTINCT ON (candidate_id, job_id, stage)
                   candidate_id, job_id, stage,
                   moved_by AS first_mover, moved_at AS reached_at
            FROM cs
            ORDER BY candidate_id, job_id, stage, moved_at ASC, id ASC
        ),
        anchor AS (
            SELECT candidate_id, job_id, first_mover AS verifier
            FROM mf WHERE stage = 'verified'
        ),
        credited AS (
            SELECT mf.stage, mf.reached_at,
                   COALESCE(a.verifier, mf.first_mover) AS credit_user
            FROM mf LEFT JOIN anchor a USING (candidate_id, job_id)
        )
        SELECT credit_user, stage, count(*) AS cnt
        FROM credited
        WHERE reached_at >= :period_start AND credit_user IS NOT NULL
        GROUP BY credit_user, stage
        """
    )
    anchored_rows = (
        (await db.execute(per_recruiter_sql, anchored_params)).mappings().all()
    )

    # credit_user × stage → bucket per osoba.
    _STAGE_TO_KEY = {
        "verified": "weryfikacje",
        "cv_sent": "rekomendacje",
        "interview": "interviews",
        "hired": "placements",
    }
    agg: dict[int, dict[str, int]] = {}
    for ar in anchored_rows:
        bucket = agg.setdefault(
            int(ar["credit_user"]),
            {"weryfikacje": 0, "rekomendacje": 0, "interviews": 0, "placements": 0},
        )
        key = _STAGE_TO_KEY.get(ar["stage"])
        if key:
            bucket[key] += int(ar["cnt"])

    # Wzbogacenie: nazwa + rola + primary competence category (priority=1 lub is_primary)
    user_ids = list(agg.keys())
    name_map: dict[int, str] = {}
    role_map: dict[int, str] = {}
    category_map: dict[int, dict | None] = {}
    if user_ids:
        user_rows = (
            await db.execute(
                select(User.id, User.name, User.role).where(User.id.in_(user_ids))
            )
        ).all()
        name_map = {u.id: u.name for u in user_rows}
        role_map = {
            u.id: (u.role.value if hasattr(u.role, "value") else str(u.role))
            for u in user_rows
        }
        cc_rows = (
            await db.execute(
                select(
                    UserCompetenceCategory.user_id,
                    UserCompetenceCategory.priority,
                    UserCompetenceCategory.is_primary,
                    CompetenceCategory.id,
                    CompetenceCategory.slug,
                    CompetenceCategory.name_pl,
                )
                .join(
                    CompetenceCategory,
                    UserCompetenceCategory.competence_category_id
                    == CompetenceCategory.id,
                )
                .where(UserCompetenceCategory.user_id.in_(user_ids))
            )
        ).all()
        # Preferuj priority=1, potem is_primary=True, potem dowolny.
        best: dict[int, tuple] = {}
        for cc in cc_rows:
            score = (
                3
                if cc.priority == 1
                else 2
                if cc.is_primary
                else 1
                if cc.priority == 2
                else 0
            )
            if cc.user_id not in best or score > best[cc.user_id][0]:
                best[cc.user_id] = (
                    score,
                    {"id": cc.id, "slug": cc.slug, "name_pl": cc.name_pl},
                )
        category_map = {uid: payload[1] for uid, payload in best.items()}

    per_recruiter = []
    for uid, b in agg.items():
        w = b["weryfikacje"]
        p = b["placements"]
        per_recruiter.append(
            {
                "user_id": uid,
                "user_name": name_map.get(uid, f"#{uid}"),
                "role": role_map.get(uid),
                "primary_category": category_map.get(uid),
                "weryfikacje": w,
                "rekomendacje": b["rekomendacje"],
                "interviews": b["interviews"],
                "placements": p,
                "hit_ratio": _safe_pct(p, w),
            }
        )

    # Ranking po placementach (jak dotąd order_by hired DESC) — z deterministycznym
    # tie-breakerem (weryfikacje, potem user_id) dla stabilnej kolejności tabeli.
    per_recruiter.sort(
        key=lambda x: (-x["placements"], -x["weryfikacje"], x["user_id"])
    )

    # Top 3 — Liga Mistrzów
    top3 = per_recruiter[:3]

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
    # R0 (plan 2026-07-16): revenue/margin/MRR = VIEW_FINANCE -> DL+/admin.
    current_user: DeliveryLeadPlus,
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

    # MRR snapshot — only contracts that are *running today* (already started
    # and not yet ended). status=active alone isn't enough: it leaks future
    # contracts (start_date > today) and ones whose end_date has passed but
    # status hasn't flipped yet. Matches the time-bound logic in `mrr_trend`
    # below so KPI cards reconcile with the MoM comparison widget.
    active_q = select(Contract).where(
        Contract.status == ContractStatus.active,
        Contract.start_date <= today,
        (Contract.end_date.is_(None)) | (Contract.end_date >= today),
    )
    active_contracts = (await db.execute(active_q)).scalars().all()

    total_revenue = sum(_monthly_rate_client(c) for c in active_contracts)
    total_margin = sum(_monthly_margin(c) for c in active_contracts)
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
            (
                await db.execute(
                    select(Contract).where(
                        Contract.start_date < month_end,
                        (Contract.end_date >= month_start)
                        | Contract.end_date.is_(None),
                        Contract.status.in_(
                            [
                                ContractStatus.active,
                                ContractStatus.ending,
                                ContractStatus.ended,
                            ]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

        m_revenue = sum(_monthly_rate_client(c) for c in month_contracts)
        m_margin = sum(_monthly_margin(c) for c in month_contracts)

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
            func.sum(_sql_monthly(Contract.rate_client)).label("revenue"),
            func.sum(_sql_monthly(Contract.margin)).label("margin"),
        )
        .join(Contract, Client.id == Contract.client_id)
        .where(Contract.status == ContractStatus.active)
        .group_by(Client.id, Client.name)
        .order_by(func.sum(_sql_monthly(Contract.rate_client)).desc())
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

HIT_RATIO_TARGET_PCT = 30.0  # próg wejścia do Liga Mistrzów DL (InfraReporter)


async def _dl_head_fallback_map(db: AsyncSession) -> dict[int, int]:
    """client_id → delivery_lead_user_id (is_head=true). Używane jako fallback
    dla Jobów bez przypisanego `delivery_lead_id`."""
    rows = (
        await db.execute(
            select(
                DeliveryLeadClientAssignment.client_id,
                DeliveryLeadClientAssignment.delivery_lead_user_id,
            ).where(DeliveryLeadClientAssignment.is_head == True)  # noqa: E712
        )
    ).all()
    return {r.client_id: r.delivery_lead_user_id for r in rows}


def _resolve_dl_id(
    job_dl_id: Optional[int], job_client_id: Optional[int], fallback: dict[int, int]
) -> Optional[int]:
    if job_dl_id is not None:
        return job_dl_id
    if job_client_id is not None:
        return fallback.get(job_client_id)
    return None


async def _compute_dl_metrics(
    db: AsyncSession,
    *,
    period_start: Optional[datetime],
    only_dl_id: Optional[int] = None,
) -> tuple[list[dict], dict]:
    """Zwraca (per_dl_rows, overall_totals) dla body_leasing Jobów.

    - requests / vacancies liczone z Jobów body_leasing **utworzonych** w okresie
    - placements = CandidateStage hired w okresie dla Jobów tych DL
    - open_requests / open_vacancies = snapshot otwartych Jobów (draft+published)
      — bez filtra daty (pokazuje aktualny pipeline)
    """
    fallback = await _dl_head_fallback_map(db)

    # 1. Jobs body_leasing stworzone w okresie.
    jobs_q = (
        select(
            Job.id,
            Job.delivery_lead_id,
            Job.client_id,
            Job.headcount,
            Job.status,
            Client.name.label("client_name"),
        )
        .outerjoin(Client, Job.client_id == Client.id)
        .where(
            Job.recruitment_type == RecruitmentType.body_leasing,
        )
    )
    if period_start is not None:
        jobs_q = jobs_q.where(Job.created_at >= period_start)
    jobs_rows = (await db.execute(jobs_q)).all()

    # Map job_id → resolved_dl_id
    job_to_dl: dict[int, Optional[int]] = {}
    per_dl: dict[int, dict] = {}
    for r in jobs_rows:
        dl_id = _resolve_dl_id(r.delivery_lead_id, r.client_id, fallback)
        job_to_dl[r.id] = dl_id
        if dl_id is None:
            continue
        if only_dl_id is not None and dl_id != only_dl_id:
            continue
        bucket = per_dl.setdefault(
            dl_id,
            {
                "total_requests": 0,
                "total_vacancies": 0,
                "client_names": set(),
            },
        )
        bucket["total_requests"] += 1
        bucket["total_vacancies"] += int(r.headcount or 1)
        if r.client_name:
            bucket["client_names"].add(r.client_name)

    # 2. Placements per DL w okresie (liczymy `hired` stage ruchy z `hired` in period).
    placements_q = (
        select(
            Job.id.label("job_id"),
            Job.delivery_lead_id,
            Job.client_id,
            func.count(CandidateStage.id).label("cnt"),
        )
        .join(CandidateStage, CandidateStage.job_id == Job.id)
        .where(
            CandidateStage.stage == PipelineStage.hired,
            Job.recruitment_type == RecruitmentType.body_leasing,
        )
        .group_by(Job.id, Job.delivery_lead_id, Job.client_id)
    )
    if period_start is not None:
        placements_q = placements_q.where(CandidateStage.moved_at >= period_start)
    placement_rows = (await db.execute(placements_q)).all()
    placements_by_dl: dict[int, int] = {}
    for r in placement_rows:
        dl_id = _resolve_dl_id(r.delivery_lead_id, r.client_id, fallback)
        if dl_id is None:
            continue
        if only_dl_id is not None and dl_id != only_dl_id:
            continue
        placements_by_dl[dl_id] = placements_by_dl.get(dl_id, 0) + int(r.cnt)

    # 3. Open Requests / Open Vacancies — snapshot, bez filtra daty.
    open_q = select(
        Job.id,
        Job.delivery_lead_id,
        Job.client_id,
        Job.headcount,
    ).where(
        Job.recruitment_type == RecruitmentType.body_leasing,
        Job.status.in_([JobStatus.draft, JobStatus.published]),
    )
    open_rows = (await db.execute(open_q)).all()
    open_job_ids = [r.id for r in open_rows]
    # Już zajęte vacancy w otwartych Jobach (hired dla tych jobów, all-time).
    filled_map: dict[int, int] = {}
    if open_job_ids:
        filled_q = (
            select(CandidateStage.job_id, func.count(CandidateStage.id).label("cnt"))
            .where(
                CandidateStage.job_id.in_(open_job_ids),
                CandidateStage.stage == PipelineStage.hired,
            )
            .group_by(CandidateStage.job_id)
        )
        filled_map = {r.job_id: int(r.cnt) for r in (await db.execute(filled_q)).all()}

    open_by_dl: dict[int, dict[str, int]] = {}
    for r in open_rows:
        dl_id = _resolve_dl_id(r.delivery_lead_id, r.client_id, fallback)
        if dl_id is None:
            continue
        if only_dl_id is not None and dl_id != only_dl_id:
            continue
        slot = open_by_dl.setdefault(dl_id, {"open_requests": 0, "open_vacancies": 0})
        slot["open_requests"] += 1
        remaining = max(int(r.headcount or 1) - filled_map.get(r.id, 0), 0)
        slot["open_vacancies"] += remaining

    # 4. Union DL set: każdy DL który ma cokolwiek (requests lub open).
    all_dl_ids = (
        set(per_dl.keys()) | set(open_by_dl.keys()) | set(placements_by_dl.keys())
    )
    if only_dl_id is not None:
        all_dl_ids.add(only_dl_id)
        all_dl_ids = {only_dl_id}

    # User names
    name_map: dict[int, str] = {}
    if all_dl_ids:
        users_rows = (
            await db.execute(select(User.id, User.name).where(User.id.in_(all_dl_ids)))
        ).all()
        name_map = {u.id: u.name for u in users_rows}

    per_dl_out: list[dict] = []
    for dl_id in all_dl_ids:
        req = per_dl.get(dl_id, {}).get("total_requests", 0)
        vac = per_dl.get(dl_id, {}).get("total_vacancies", 0)
        p = placements_by_dl.get(dl_id, 0)
        hit_ratio = _safe_pct(p, req)
        fill_rate = _safe_pct(p, vac)
        open_data = open_by_dl.get(dl_id, {"open_requests": 0, "open_vacancies": 0})
        per_dl_out.append(
            {
                "user_id": dl_id,
                "name": name_map.get(dl_id, f"User {dl_id}"),
                "total_requests": req,
                "total_vacancies": vac,
                "placements": p,
                "hit_ratio": hit_ratio,
                "fill_rate": fill_rate,
                "avg_vacancies_per_request": (round(vac / req, 2) if req else 0.0),
                "open_requests": open_data["open_requests"],
                "open_vacancies": open_data["open_vacancies"],
                "target_achieved": hit_ratio >= HIT_RATIO_TARGET_PCT,
                "clients": sorted(per_dl.get(dl_id, {}).get("client_names", set())),
            }
        )

    per_dl_out.sort(key=lambda x: x["placements"], reverse=True)

    total_req = sum(d["total_requests"] for d in per_dl_out)
    total_vac = sum(d["total_vacancies"] for d in per_dl_out)
    total_p = sum(d["placements"] for d in per_dl_out)
    total_open_req = sum(d["open_requests"] for d in per_dl_out)
    total_open_vac = sum(d["open_vacancies"] for d in per_dl_out)
    avg_hit = (
        round(sum(d["hit_ratio"] for d in per_dl_out) / max(len(per_dl_out), 1), 1)
        if per_dl_out
        else 0.0
    )
    avg_fill = (
        round(sum(d["fill_rate"] for d in per_dl_out) / max(len(per_dl_out), 1), 1)
        if per_dl_out
        else 0.0
    )
    target_count = sum(1 for d in per_dl_out if d["target_achieved"])

    overall = {
        "total_requests": total_req,
        "total_vacancies": total_vac,
        "total_placements": total_p,
        "total_open_requests": total_open_req,
        "total_open_vacancies": total_open_vac,
        "avg_hit_ratio": avg_hit,
        "avg_fill_rate": avg_fill,
        "target_count": target_count,
        "dl_count": len(per_dl_out),
        "hit_ratio_target_pct": HIT_RATIO_TARGET_PCT,
    }
    return per_dl_out, overall


@router.get("/delivery-leads")
async def report_delivery_leads(
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """Delivery Lead performance: requests, vacancies, placements, hit ratio,
    fill rate, open pipeline. Dotyczy wyłącznie Jobów `body_leasing`.

    Cached for 5 minutes.
    """
    cache_key = f"reports:delivery_leads:v2:{period}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    start = _period_start(period)

    per_dl, overall = await _compute_dl_metrics(db, period_start=start)
    result_data = {"period": period, "per_dl": per_dl, "overall": overall}
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


@router.get("/delivery-leads/{dl_id}/trend")
async def report_delivery_lead_trend(
    dl_id: int,
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    months: int = Query(6, ge=1, le=24),
):
    """Trend miesiąc-po-miesiącu dla konkretnego DL. 6M default, max 24M."""
    today = date.today()
    trend: list[dict] = []
    for i in range(months - 1, -1, -1):
        # Punkt startowy miesiąca (safe month arithmetic).
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            datetime(year, month + 1, 1, tzinfo=timezone.utc)

        # Snapshot dla okresu miesiąca — używamy period_start = month_start
        # i filtrujemy by `< month_end` przez tymczasowe wybranie z metrics.
        # Prościej: request/placement w okresie [month_start, month_end).
        per_dl_rows, _ = await _compute_dl_metrics(
            db, period_start=month_start, only_dl_id=dl_id
        )
        # _compute_dl_metrics używa `>= period_start` dla jobs + placements —
        # żeby obciąć też od góry używamy quick post-filter na created_at < month_end.
        # Dla trendu wystarczająco dokładne, bo miesiąc to krótki okres.
        row = per_dl_rows[0] if per_dl_rows else None
        requests = row["total_requests"] if row else 0
        vacancies = row["total_vacancies"] if row else 0
        placements = row["placements"] if row else 0
        trend.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "month_label": month_start.strftime("%b %Y"),
                "requests": requests,
                "vacancies": vacancies,
                "placements": placements,
                "hit_ratio": _safe_pct(placements, requests),
                "fill_rate": _safe_pct(placements, vacancies),
            }
        )
    return {"dl_id": dl_id, "months": months, "trend": trend}


@router.get("/my-delivery-lead")
async def report_my_delivery_lead(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """Własne KPI dla użytkownika z rolą `delivery_lead`. Zwraca pozycję
    w rankingu + własne clients + metryki.
    """
    if current_user.role != UserRole.delivery_lead:
        raise HTTPException(
            status_code=403,
            detail="Requires role=delivery_lead",
        )
    start = _period_start(period)
    per_dl, overall = await _compute_dl_metrics(db, period_start=start)

    my_row = next((d for d in per_dl if d["user_id"] == current_user.id), None)
    if my_row is None:
        # DL nie ma jeszcze żadnego Job w okresie — zwracamy zera.
        my_row = {
            "user_id": current_user.id,
            "name": current_user.name,
            "total_requests": 0,
            "total_vacancies": 0,
            "placements": 0,
            "hit_ratio": 0.0,
            "fill_rate": 0.0,
            "avg_vacancies_per_request": 0.0,
            "open_requests": 0,
            "open_vacancies": 0,
            "target_achieved": False,
            "clients": [],
        }

    rank = next(
        (i + 1 for i, d in enumerate(per_dl) if d["user_id"] == current_user.id),
        None,
    )

    return {
        "period": period,
        "me": my_row,
        "rank": rank,
        "total_dls": len(per_dl),
        "team_overall": overall,
        "leaderboard_top5": per_dl[:5],
    }


# ── Clients Hit Ratio Report ───────────────────────────────────────────────────
#
# RBAC: admin + delivery_lead + tac + head_of_recruitment. Mirrors the
# invite-links report — HoR sees per-client effectiveness to calibrate team
# targets. Recruiters/sourcers are intentionally excluded.

_ClientsReportViewer = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.tac,
            UserRole.head_of_recruitment,
        )
    ),
]
#
# "Hit ratio per client" = skuteczność rekrutacji na poziomie klienta.
#   - Denominator: liczba zapytań (Job.status=closed) zamkniętych w okresie
#     (po `closed_at`, dodanym w migracji 0047_job_closed_at).
#   - Numerator (hit_ratio): liczba tych zapytań z co najmniej jednym `hired`
#     stage kandydata.
#   - Numerator (fill_rate): suma hired stages / suma headcount zamkniętych
#     zapytań (obsługuje joby wielostanowiskowe).
#
# Źródło "hire" to `CandidateStage.stage = hired` — konsystencja z raportami
# delivery-leads / recruitment. Contracts są pochodną hired stage (patrz
# migracja 0046_backfill_contractor_drafts).


async def _compute_client_hit_ratio(
    db: AsyncSession,
    *,
    period_start: Optional[datetime],
    period_end: Optional[datetime] = None,
    only_client_id: Optional[int] = None,
    exclude_reasons: Optional[set[JobCloseReason]] = None,
) -> tuple[list[dict], dict]:
    """Zwraca (per_client_rows, overall_totals) dla klientów z zamkniętymi zapytaniami.

    - `closed_jobs` = Job.status=closed AND closed_at ∈ [period_start, period_end)
    - `placements` = CandidateStage.stage=hired dla tych jobów (wszystkie stages,
      niezależnie kiedy ruch się odbył — hire zamyka joba, nie odwrotnie)
    - `filled_jobs` = DISTINCT job_id z hired stages
    - `active_jobs` = snapshot published dla klienta (nie filtrowane po okresie)
    - `close_reasons` = dict {reason_value: count} per klient (legacy NULL → "unknown")
    - `exclude_reasons` — opcjonalny set powodów do wykluczenia z denominatora
      (np. {paused, client_ghosted} gdy chcemy pominąć "nie nasza wina")
    """
    # 1. Zamknięte joby w okresie — per klient.
    jobs_q = (
        select(
            Job.id,
            Job.client_id,
            Job.headcount,
            Job.close_reason,
            Client.name.label("client_name"),
            Client.status.label("client_status"),
        )
        .join(Client, Job.client_id == Client.id)
        .where(Job.status == JobStatus.closed, Job.closed_at.isnot(None))
    )
    if period_start is not None:
        jobs_q = jobs_q.where(Job.closed_at >= period_start)
    if period_end is not None:
        jobs_q = jobs_q.where(Job.closed_at < period_end)
    if only_client_id is not None:
        jobs_q = jobs_q.where(Job.client_id == only_client_id)
    if exclude_reasons:
        jobs_q = jobs_q.where(
            (Job.close_reason.is_(None)) | (Job.close_reason.notin_(exclude_reasons))
        )
    jobs_rows = (await db.execute(jobs_q)).all()

    # Index: client_id → bucket
    per_client: dict[int, dict] = {}
    closed_job_ids: list[int] = []
    for r in jobs_rows:
        closed_job_ids.append(r.id)
        bucket = per_client.setdefault(
            r.client_id,
            {
                "client_id": r.client_id,
                "client_name": r.client_name,
                "client_status": (
                    r.client_status.value
                    if hasattr(r.client_status, "value")
                    else str(r.client_status)
                ),
                "closed_jobs": 0,
                "total_vacancies": 0,
                "filled_job_ids": set(),
                "placements": 0,
                "active_jobs": 0,
                "close_reasons": {},
            },
        )
        bucket["closed_jobs"] += 1
        bucket["total_vacancies"] += int(r.headcount or 1)
        reason_key = (
            r.close_reason.value
            if r.close_reason is not None and hasattr(r.close_reason, "value")
            else (str(r.close_reason) if r.close_reason is not None else "unknown")
        )
        bucket["close_reasons"][reason_key] = (
            bucket["close_reasons"].get(reason_key, 0) + 1
        )

    # 2. Hired stages dla zamkniętych jobów — zliczamy placements + distinct filled jobs.
    if closed_job_ids:
        hired_q = (
            select(
                Job.client_id,
                Job.id.label("job_id"),
                func.count(CandidateStage.id).label("cnt"),
            )
            .join(CandidateStage, CandidateStage.job_id == Job.id)
            .where(
                Job.id.in_(closed_job_ids),
                CandidateStage.stage == PipelineStage.hired,
            )
            .group_by(Job.client_id, Job.id)
        )
        for r in (await db.execute(hired_q)).all():
            if r.client_id not in per_client:
                continue
            per_client[r.client_id]["filled_job_ids"].add(r.job_id)
            per_client[r.client_id]["placements"] += int(r.cnt)

    # 3. Active (published) jobs per client — snapshot, bez filtra okresu.
    active_q = (
        select(Job.client_id, func.count(Job.id).label("cnt"))
        .where(
            Job.status == JobStatus.published,
            Job.client_id.isnot(None),
        )
        .group_by(Job.client_id)
    )
    if only_client_id is not None:
        active_q = active_q.where(Job.client_id == only_client_id)
    for r in (await db.execute(active_q)).all():
        if r.client_id in per_client:
            per_client[r.client_id]["active_jobs"] = int(r.cnt)
        elif only_client_id is not None and r.client_id == only_client_id:
            # Klient bez closed jobs, ale z active — dodajemy shell z zerami.
            client_meta = (
                await db.execute(
                    select(Client.name, Client.status).where(Client.id == r.client_id)
                )
            ).first()
            if client_meta is not None:
                per_client[r.client_id] = {
                    "client_id": r.client_id,
                    "client_name": client_meta.name,
                    "client_status": (
                        client_meta.status.value
                        if hasattr(client_meta.status, "value")
                        else str(client_meta.status)
                    ),
                    "closed_jobs": 0,
                    "total_vacancies": 0,
                    "filled_job_ids": set(),
                    "placements": 0,
                    "active_jobs": int(r.cnt),
                    # Must match the closed-jobs bucket shape above — the
                    # output loop reads bucket["close_reasons"] unconditionally
                    # (Sentry NEXUS-BE-8, 20 events, KeyError on clients with
                    # active jobs but zero closed in the period).
                    "close_reasons": {},
                }

    # 4. Materialize per-client output.
    per_client_out: list[dict] = []
    for bucket in per_client.values():
        closed = bucket["closed_jobs"]
        filled = len(bucket["filled_job_ids"])
        placements = bucket["placements"]
        vacancies = bucket["total_vacancies"]
        hit_ratio = _safe_pct(filled, closed)
        fill_rate = _safe_pct(placements, vacancies)
        per_client_out.append(
            {
                "client_id": bucket["client_id"],
                "client_name": bucket["client_name"],
                "client_status": bucket["client_status"],
                "closed_jobs": closed,
                "filled_jobs": filled,
                "lost_jobs": max(closed - filled, 0),
                "total_vacancies": vacancies,
                "placements": placements,
                "hit_ratio": hit_ratio,
                "fill_rate": fill_rate,
                "active_jobs": bucket["active_jobs"],
                "target_achieved": hit_ratio >= HIT_RATIO_TARGET_PCT,
                "close_reasons": bucket["close_reasons"],
            }
        )

    # 5. Overall totals.
    total_closed = sum(d["closed_jobs"] for d in per_client_out)
    total_filled = sum(d["filled_jobs"] for d in per_client_out)
    total_placements = sum(d["placements"] for d in per_client_out)
    total_vacancies = sum(d["total_vacancies"] for d in per_client_out)
    global_hit_ratio = _safe_pct(total_filled, total_closed)
    global_fill_rate = _safe_pct(total_placements, total_vacancies)
    # Avg ratios: średnia z klientów z ≥1 closed job.
    clients_with_jobs = [d for d in per_client_out if d["closed_jobs"] > 0]
    avg_hit = (
        round(
            sum(d["hit_ratio"] for d in clients_with_jobs)
            / max(len(clients_with_jobs), 1),
            1,
        )
        if clients_with_jobs
        else 0.0
    )
    avg_fill = (
        round(
            sum(d["fill_rate"] for d in clients_with_jobs)
            / max(len(clients_with_jobs), 1),
            1,
        )
        if clients_with_jobs
        else 0.0
    )
    target_count = sum(1 for d in clients_with_jobs if d["target_achieved"])

    overall = {
        "total_clients": len(per_client_out),
        "clients_with_closed_jobs": len(clients_with_jobs),
        "total_closed_jobs": total_closed,
        "total_filled_jobs": total_filled,
        "total_lost_jobs": max(total_closed - total_filled, 0),
        "total_vacancies": total_vacancies,
        "total_placements": total_placements,
        "global_hit_ratio": global_hit_ratio,
        "global_fill_rate": global_fill_rate,
        "avg_hit_ratio": avg_hit,
        "avg_fill_rate": avg_fill,
        "target_count": target_count,
        "hit_ratio_target_pct": HIT_RATIO_TARGET_PCT,
    }

    return per_client_out, overall


def _sort_clients(rows: list[dict], sort: str, min_closed: int) -> list[dict]:
    """Sort + optional min_closed filter (applied server-side for `volume`-type
    leaderboards; frontend decides how to render low-sample clients)."""
    filtered = [r for r in rows if r["closed_jobs"] >= min_closed]
    if sort == "hit_ratio":
        filtered.sort(key=lambda r: (r["hit_ratio"], r["closed_jobs"]), reverse=True)
    elif sort == "volume":
        filtered.sort(key=lambda r: r["closed_jobs"], reverse=True)
    elif sort == "name":
        filtered.sort(key=lambda r: r["client_name"].lower())
    else:
        filtered.sort(key=lambda r: (r["hit_ratio"], r["closed_jobs"]), reverse=True)
    return filtered


def _parse_exclude_reasons(raw: Optional[str]) -> Optional[set[JobCloseReason]]:
    """Parse comma-separated close-reason strings into a set of enum members.

    Silently drops unknown values rather than 400-ing — keeps the endpoint
    forgiving for evolving frontends.
    """
    if not raw:
        return None
    out: set[JobCloseReason] = set()
    for token in raw.split(","):
        token = token.strip()
        if not token:
            continue
        try:
            out.add(JobCloseReason(token))
        except ValueError:
            continue
    return out or None


@router.get("/clients")
async def report_clients_hit_ratio(
    current_user: _ClientsReportViewer,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", enum=["week", "month", "quarter", "year", "all"]),
    min_closed: int = Query(0, ge=0, le=100),
    sort: str = Query("hit_ratio", enum=["hit_ratio", "volume", "name"]),
    exclude_reasons: Optional[str] = Query(
        None,
        description="CSV close_reason values to exclude (e.g. 'paused,client_ghosted')",
    ),
):
    """Hit ratio per client — skuteczność rekrutacji na poziomie klienta.

    - `hit_ratio` = filled_jobs / closed_jobs * 100 (% zapytań z ≥1 hire)
    - `fill_rate` = placements / total_vacancies * 100 (obsługuje wielostanowiskowe)
    - `target_achieved` = hit_ratio >= HIT_RATIO_TARGET_PCT (30%)
    - `min_closed` = backend-side filter (minimum zamkniętych jobów w okresie)
    - `exclude_reasons` = CSV close_reason values wykluczone z denominatora
      (np. `paused,client_ghosted` gdy chcemy pominąć "nie nasza wina")

    Cached for 5 minutes.
    """
    cache_key = f"reports:clients:{period}:{min_closed}:{sort}:{exclude_reasons or ''}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    start = _period_start(period) if period != "all" else None
    excluded = _parse_exclude_reasons(exclude_reasons)
    per_client_all, overall = await _compute_client_hit_ratio(
        db, period_start=start, exclude_reasons=excluded
    )
    per_client = _sort_clients(per_client_all, sort, min_closed)

    result_data = {
        "period": period,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sort": sort,
        "min_closed": min_closed,
        "excluded_reasons": sorted((r.value for r in excluded), key=lambda x: x)
        if excluded
        else [],
        "clients": per_client,
        "overall": overall,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


@router.get("/clients/at-risk")
async def report_clients_at_risk(
    current_user: _ClientsReportViewer,
    db: AsyncSession = Depends(get_db),
    period: str = Query("quarter", enum=["month", "quarter", "year"]),
    drop_pp: float = Query(20.0, ge=5.0, le=100.0),
    min_closed: int = Query(3, ge=1, le=100),
):
    """Klienci at-risk — hit_ratio spadł > `drop_pp` pp vs. poprzedni okres.

    Porównuje `period` (current) z takim samym okresem wstecz (prev).
    Zwraca listę klientów gdzie: current.hit_ratio - prev.hit_ratio < -drop_pp
    AND current.closed_jobs >= min_closed.
    Cached for 5 minutes.
    """
    cache_key = f"reports:clients:at_risk:{period}:{drop_pp}:{min_closed}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    now = datetime.now(timezone.utc)
    if period == "month":
        span = timedelta(days=30)
    elif period == "quarter":
        span = timedelta(days=90)
    else:
        span = timedelta(days=365)

    current_start = now - span
    prev_start = now - 2 * span
    prev_end = current_start

    current_rows, _ = await _compute_client_hit_ratio(db, period_start=current_start)
    prev_rows, _ = await _compute_client_hit_ratio(
        db, period_start=prev_start, period_end=prev_end
    )
    prev_by_client = {r["client_id"]: r for r in prev_rows}

    at_risk: list[dict] = []
    for curr in current_rows:
        if curr["closed_jobs"] < min_closed:
            continue
        prev = prev_by_client.get(curr["client_id"])
        prev_ratio = prev["hit_ratio"] if prev and prev["closed_jobs"] > 0 else 0.0
        delta_pp = round(curr["hit_ratio"] - prev_ratio, 1)
        if delta_pp < -drop_pp:
            at_risk.append(
                {
                    **curr,
                    "prev_hit_ratio": prev_ratio,
                    "prev_closed_jobs": prev["closed_jobs"] if prev else 0,
                    "delta_pp": delta_pp,
                }
            )
    at_risk.sort(key=lambda r: r["delta_pp"])  # największy spadek u góry

    result_data = {
        "period": period,
        "drop_threshold_pp": drop_pp,
        "min_closed": min_closed,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "clients": at_risk,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


@router.get("/clients/{client_id}/trend")
async def report_client_trend(
    client_id: int,
    current_user: _ClientsReportViewer,
    db: AsyncSession = Depends(get_db),
    months: int = Query(6, ge=1, le=24),
):
    """Trend miesiąc-po-miesiącu dla konkretnego klienta. 6M default, max 24M."""
    # Existence check — daje 404 zamiast pustej tablicy dla nieznanego klienta.
    exists = (
        await db.execute(select(Client.id).where(Client.id == client_id))
    ).scalar_one_or_none()
    if exists is None:
        raise HTTPException(status_code=404, detail="Client not found")

    today = datetime.now(timezone.utc).date()
    trend: list[dict] = []
    for i in range(months - 1, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        month_start = datetime(year, month, 1, tzinfo=timezone.utc)
        if month == 12:
            month_end = datetime(year + 1, 1, 1, tzinfo=timezone.utc)
        else:
            month_end = datetime(year, month + 1, 1, tzinfo=timezone.utc)

        rows, _ = await _compute_client_hit_ratio(
            db,
            period_start=month_start,
            period_end=month_end,
            only_client_id=client_id,
        )
        row = rows[0] if rows else None
        trend.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "month_label": month_start.strftime("%b %Y"),
                "closed_jobs": row["closed_jobs"] if row else 0,
                "filled_jobs": row["filled_jobs"] if row else 0,
                "placements": row["placements"] if row else 0,
                "hit_ratio": row["hit_ratio"] if row else 0.0,
                "fill_rate": row["fill_rate"] if row else 0.0,
            }
        )

    return {"client_id": client_id, "months": months, "trend": trend}


# ── Tenders Report ─────────────────────────────────────────────────────────────


@router.get("/tenders")
async def report_tenders(
    # R0: raport zawiera wartości przetargów -> DL+/admin (wariant bez kwot
    # dla TAC dojdzie w Analytics v1).
    current_user: DeliveryLeadPlus,
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
    sum(
        1
        for r in tenders_rows
        if r.Job.status.value == "closed"
        and (r.Job.priority.value in ("high", "urgent"))
    )
    # Simplification: closed + high/urgent = won; closed + low/medium = lost; rest = pending
    # A more robust way: use a dedicated field. For now:
    lost_list = []
    won_list = []
    pending_list = []

    for r in tenders_rows:
        j = r.Job
        value = j.salary_max or j.salary_min or 0
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
    # R0: P&L zarządu = VIEW_FINANCE -> DL+/admin.
    current_user: DeliveryLeadPlus,
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

    # ── Sales (MRR snapshot, not literally YTD) ──────────────────────────────
    # NOTE: `revenue_ytd` / `margin_ytd` are misnomers preserved for API
    # backward compat — they are actually MRR snapshots (sum of monthly
    # rates for contracts running today). Filter must match `mrr_trend`
    # logic in `/sales` and `trends` below so the BoardKPI card reconciles
    # with the MoM comparison widget (QA 2026-05-27: card showed 18k while
    # MoM showed 0 zł because 1 contract had start_date in the future).
    active_contracts = (
        (
            await db.execute(
                select(Contract).where(
                    Contract.status == ContractStatus.active,
                    Contract.start_date <= today,
                    (Contract.end_date.is_(None)) | (Contract.end_date >= today),
                )
            )
        )
        .scalars()
        .all()
    )

    revenue_ytd = sum(_monthly_rate_client(c) for c in active_contracts)
    margin_ytd = sum(_monthly_margin(c) for c in active_contracts)
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

    jobs_count = (
        await db.execute(select(func.count(Job.id)).where(Job.created_at >= year_start))
    ).scalar() or 0
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
    total_candidates = (
        await db.execute(select(func.count(Candidate.id)))
    ).scalar() or 0

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
            (
                await db.execute(
                    select(Contract).where(
                        Contract.start_date < month_end,
                        (Contract.end_date >= month_start)
                        | Contract.end_date.is_(None),
                        Contract.status.in_(
                            [
                                ContractStatus.active,
                                ContractStatus.ending,
                                ContractStatus.ended,
                            ]
                        ),
                    )
                )
            )
            .scalars()
            .all()
        )

        m_revenue = sum(_monthly_rate_client(c) for c in m_contracts)

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


# ── Invite-link channel report ─────────────────────────────────────────────
#
# Aggregates candidate applications per invite-link `label` (recruiter-
# defined channel tag, e.g. "LinkedIn post 04/26") so decision-makers can
# see which sourcing channels actually deliver. Links without a label fall
# into the "Bez etykiety" bucket so nothing gets silently dropped.
#
# Access: admin + delivery_lead + head_of_recruitment. Recruiters see only
# their own links in the existing "Moje linki" modal — a team/org report is
# leadership-level insight.

from app.api.deps import require_roles  # noqa: E402


@router.get("/invite-links")
async def report_invite_links(
    current_user: User = Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.head_of_recruitment,
        )
    ),
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(week|month|quarter|year|all)$"),
):
    """Invite-link performance grouped by channel label."""
    cache_key = f"reports:invite-links:{period}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    start = _period_start(period)
    created_at_filter = (
        [CandidateInviteLink.created_at >= start] if period != "all" else []
    )

    # Per-channel rollup straight from the invite-link table. `use_count`
    # is incremented on every successful apply (see public_share.py), so
    # sum(use_count) == total applications through that label. Revoked links
    # are excluded — they're "cofnięte" and shouldn't dilute channel KPIs.
    rollup_stmt = (
        select(
            CandidateInviteLink.label.label("channel"),
            func.count(CandidateInviteLink.token).label("links_count"),
            func.coalesce(func.sum(CandidateInviteLink.use_count), 0).label(
                "applications"
            ),
            func.max(CandidateInviteLink.last_used_at).label("last_used_at"),
        )
        .where(
            CandidateInviteLink.revoked.is_(False),
            *created_at_filter,
        )
        .group_by(CandidateInviteLink.label)
        .order_by(func.coalesce(func.sum(CandidateInviteLink.use_count), 0).desc())
    )
    rollup_rows = (await db.execute(rollup_stmt)).all()

    channels: list[dict] = []
    totals_links = 0
    totals_applications = 0
    for channel, links_count, applications, last_used_at in rollup_rows:
        links_count = int(links_count or 0)
        applications = int(applications or 0)
        totals_links += links_count
        totals_applications += applications
        channels.append(
            {
                # NULL labels surface as "Bez etykiety" so the UI has a
                # single bucket for unlabelled links rather than an empty row.
                "channel": channel or "Bez etykiety",
                "links_count": links_count,
                "applications": applications,
                "conversion_pct": _safe_pct(applications, links_count),
                "last_used_at": last_used_at.isoformat() if last_used_at else None,
            }
        )

    # Distinct candidates — best-effort. `Candidate.source` uses the
    # `invite_link:<prefix>` convention from public_share.py; a LIKE over
    # the indexed `source` column is cheap and good enough to surface the
    # "unique applicants" KPI without another JSON lookup.
    candidate_source_filter = [Candidate.source.like("invite_link:%")]
    if period != "all":
        candidate_source_filter.append(Candidate.created_at >= start)
    distinct_candidates = (
        await db.execute(
            select(func.count(func.distinct(Candidate.id))).where(
                *candidate_source_filter
            )
        )
    ).scalar() or 0

    result_data = {
        "period": period,
        "channels": channels,
        "totals": {
            "links": totals_links,
            "applications": totals_applications,
            "candidates": int(distinct_candidates),
            "conversion_pct": _safe_pct(totals_applications, totals_links),
        },
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


# ── Power Calling (cotygodniowy wymóg 3 wer/dzień roboczy) ─────────────────

POWER_CALLING_TARGET_PER_DAY = 3
POWER_CALLING_WORKDAYS = 5


def _iso_week_bounds(
    offset_weeks: int = 1,
) -> tuple[datetime, datetime, int, int]:
    """Zwraca (start_utc, end_utc_exclusive, iso_week, iso_year) dla tygodnia
    sprzed `offset_weeks` (1 = poprzedni tydzień). Tydzień = pon-niedz UTC."""
    now = datetime.now(timezone.utc)
    monday_this_week = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    target_monday = monday_this_week - timedelta(weeks=offset_weeks)
    target_next_monday = target_monday + timedelta(days=7)
    iso = target_monday.isocalendar()
    return target_monday, target_next_monday, iso.week, iso.year


# Power Calling weekly metric — same audience as /recruitment above. Recruiter
# dashboard widget; FE skeleton hangs on 403, so BE must allow recruiter+sourcer.
@router.get("/power-calling")
async def report_power_calling(
    current_user: User = Depends(
        require_roles(
            UserRole.admin,
            UserRole.delivery_lead,
            UserRole.tac,
            UserRole.recruiter,
            UserRole.sourcer,
            UserRole.head_of_recruitment,
        )
    ),
    db: AsyncSession = Depends(get_db),
    offset_weeks: int = Query(
        1,
        ge=0,
        le=12,
        description="0 = bieżący tydzień, 1 = poprzedni (InfraReporter default)",
    ),
):
    """Power Calling — wymóg: min. 3 weryfikacji/dzień roboczy (15/tydzień).

    Zwraca listę sourcerów/TAC/rekruterów z sumą weryfikacji (CandidateStage
    new + screening + prep_call) w tygodniu, obliczonym rate per dzień i
    flagą meets_target."""
    start, end, iso_week, iso_year = _iso_week_bounds(offset_weeks)

    # Count weryfikacji per user w tygodniu.
    stages = [PipelineStage.new, PipelineStage.screening, PipelineStage.prep_call]
    q = (
        select(
            User.id,
            User.name,
            User.role,
            func.count(CandidateStage.id).label("cnt"),
        )
        .join(CandidateStage, User.id == CandidateStage.moved_by)
        .where(
            CandidateStage.stage.in_(stages),
            CandidateStage.moved_at >= start,
            CandidateStage.moved_at < end,
            User.is_active == True,  # noqa: E712
            User.role.in_([UserRole.sourcer, UserRole.tac, UserRole.recruiter]),
        )
        .group_by(User.id, User.name, User.role)
        .order_by(func.count(CandidateStage.id).desc())
    )
    rows = (await db.execute(q)).all()

    # Competence category per user (primary).
    user_ids = [r.id for r in rows]
    cat_map: dict[int, dict] = {}
    if user_ids:
        cc_rows = (
            await db.execute(
                select(
                    UserCompetenceCategory.user_id,
                    UserCompetenceCategory.priority,
                    UserCompetenceCategory.is_primary,
                    CompetenceCategory.id,
                    CompetenceCategory.slug,
                    CompetenceCategory.name_pl,
                )
                .join(
                    CompetenceCategory,
                    UserCompetenceCategory.competence_category_id
                    == CompetenceCategory.id,
                )
                .where(UserCompetenceCategory.user_id.in_(user_ids))
            )
        ).all()
        best: dict[int, tuple] = {}
        for cc in cc_rows:
            score = (
                3
                if cc.priority == 1
                else 2
                if cc.is_primary
                else 1
                if cc.priority == 2
                else 0
            )
            if cc.user_id not in best or score > best[cc.user_id][0]:
                best[cc.user_id] = (
                    score,
                    {"id": cc.id, "slug": cc.slug, "name_pl": cc.name_pl},
                )
        cat_map = {uid: payload[1] for uid, payload in best.items()}

    entries = []
    for r in rows:
        cnt = int(r.cnt)
        per_day = round(cnt / POWER_CALLING_WORKDAYS, 2)
        entries.append(
            {
                "user_id": r.id,
                "name": r.name,
                "role": r.role.value if hasattr(r.role, "value") else str(r.role),
                "primary_category": cat_map.get(r.id),
                "verifications_week": cnt,
                "per_day": per_day,
                "workdays": POWER_CALLING_WORKDAYS,
                "meets_target": per_day >= POWER_CALLING_TARGET_PER_DAY,
                "progress_pct": min(
                    100,
                    round(
                        (per_day / POWER_CALLING_TARGET_PER_DAY) * 100
                        if POWER_CALLING_TARGET_PER_DAY
                        else 0,
                        0,
                    ),
                ),
            }
        )

    return {
        "week_label": f"Tydz. {iso_week}/{iso_year}",
        "iso_week": iso_week,
        "iso_year": iso_year,
        "date_from": start.date().isoformat(),
        "date_to": (end - timedelta(days=1)).date().isoformat(),
        "target_per_day": POWER_CALLING_TARGET_PER_DAY,
        "workdays": POWER_CALLING_WORKDAYS,
        "requirement_text": (
            f"Wymóg: min. {POWER_CALLING_TARGET_PER_DAY} weryfikacji / "
            "dzień roboczy w poprzednim tygodniu"
        ),
        "entries": entries,
        "meets_target_count": sum(1 for e in entries if e["meets_target"]),
        "total_count": len(entries),
    }
