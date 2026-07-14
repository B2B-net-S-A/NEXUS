"""
Nexus ATS — Reporting Module
Generates live reports from ATS data (recruitment, sales, delivery, tenders, board).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DeliveryLeadPlus, TacPlus, require_roles
from app.analytics.periods import AnalyticsPeriod, AnalyticsPeriodKind, resolve_period
from app.analytics.scope import (
    delivery_lead_scope,
    operations_client_scope,
    require_client_scope,
    tender_client_scope,
)
from app.core.config import settings
from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.competence_category import (
    CompetenceCategory,
    UserCompetenceCategory,
)
from app.models.contract import Contract
from app.models.invite_link import CandidateInviteLink
from app.models.job import Job, JobCloseReason, JobStatus, RecruitmentType
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.services.kpi_panel import _ANCHOR_LOOKBACK_DAYS
from app.services.analytics_v1 import AnalyticsManagerService, AnalyticsV1Service

router = APIRouter()

WARSAW = ZoneInfo("Europe/Warsaw")


# ── Helpers ────────────────────────────────────────────────────────────────────


def _period_start(period: str) -> datetime:
    """Return a calendar-period start in Europe/Warsaw, converted to UTC."""
    now = datetime.now(WARSAW)
    if period == "week":
        start = (now - timedelta(days=now.weekday())).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
    elif period == "month":
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    elif period == "quarter":
        quarter_month = ((now.month - 1) // 3) * 3 + 1
        start = now.replace(
            month=quarter_month,
            day=1,
            hour=0,
            minute=0,
            second=0,
            microsecond=0,
        )
    elif period == "year":
        start = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        return datetime.min.replace(tzinfo=timezone.utc)  # all time
    return start.astimezone(timezone.utc)


def _safe_pct(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return round(numerator / denominator * 100, 1)


def _first_milestone_subquery(stage: PipelineStage):
    """First occurrence of a milestone for every candidate x job pair.

    Legacy reports use this subquery so they reconcile with analytics v1 even
    before callers are migrated to the new response envelope.  Counting raw
    ``candidate_stages`` rows would double count candidates moved out of and
    back into a stage.
    """

    return (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            CandidateStage.job_id.label("job_id"),
            func.min(CandidateStage.moved_at).label("reached_at"),
        )
        .where(CandidateStage.stage == stage)
        .group_by(CandidateStage.candidate_id, CandidateStage.job_id)
        .subquery()
    )


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

    # Global funnel counts (across all recruiters). Definicje KPI Artura
    # (spójne z panelem „Moje KPI" / app/services/kpi_panel.py):
    # Weryfikacje    = verified    (kandydat zweryfikowany przez rekrutera)
    # Rekomendacje   = cv_sent     (CV wysłane do klienta)
    # Interviews     = interview   (zaproszenie na interview; client_interview
    #                               jest w praktyce nieużywany)
    # Placements     = hired       (kontrakt aktywny)

    canonical_stages = [
        PipelineStage.verified,
        PipelineStage.cv_sent,
        PipelineStage.interview,
        PipelineStage.client_interview,
        PipelineStage.hired,
    ]
    first_milestones = (
        select(
            CandidateStage.candidate_id.label("candidate_id"),
            CandidateStage.job_id.label("job_id"),
            CandidateStage.stage.label("stage"),
            func.min(CandidateStage.moved_at).label("reached_at"),
        )
        .where(CandidateStage.stage.in_(canonical_stages))
        .group_by(
            CandidateStage.candidate_id,
            CandidateStage.job_id,
            CandidateStage.stage,
        )
        .subquery()
    )

    async def count_stage(stages: list[PipelineStage]) -> int:
        q = (
            select(func.count())
            .select_from(first_milestones)
            .join(Job, first_milestones.c.job_id == Job.id)
            .where(
                first_milestones.c.stage.in_(stages),
                first_milestones.c.reached_at >= start,
                *job_filter,
            )
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

    generated_at = datetime.now(WARSAW)
    today = generated_at.date()
    year_period = resolve_period(AnalyticsPeriodKind.year, now=generated_at)
    manager = AnalyticsManagerService(db)
    summary = await manager.finance_summary(year_period, generated_at=generated_at)
    trend = await manager.finance_trend(year_period)
    clients = await manager.finance_clients(year_period, generated_at=generated_at)

    first_of_month = today.replace(day=1)
    next_month = (
        date(today.year + 1, 1, 1)
        if today.month == 12
        else date(today.year, today.month + 1, 1)
    )
    new_this_month = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.created_at
                >= datetime.combine(first_of_month, datetime.min.time(), tzinfo=WARSAW),
                Contract.created_at
                < datetime.combine(next_month, datetime.min.time(), tzinfo=WARSAW),
            )
        )
    ).scalar() or 0

    cutoff = today + timedelta(days=30)
    ending_rows = (
        await db.execute(
            select(Contract.id, Contract.end_date, Client.name.label("client_name"))
            .join(Client, Contract.client_id == Client.id)
            .where(
                Contract.start_date.isnot(None),
                Contract.start_date <= today,
                Contract.end_date.isnot(None),
                Contract.end_date >= today,
                Contract.end_date <= cutoff,
            )
            .order_by(Contract.end_date, Contract.id)
        )
    ).all()
    # The legacy adapter deliberately omits raw unit rates. Monetary values are
    # available only through the PLN finance schemas.
    ending_contracts_30days = [
        {
            "contract_id": row.id,
            "client_name": row.client_name,
            "end_date": str(row.end_date),
            "rate_client": None,
        }
        for row in ending_rows
    ]

    mrr_trend = [
        {
            "month": point.month,
            "month_label": point.month,
            "revenue": point.totals.revenue,
            "margin": point.totals.margin,
            "consultants": point.active_contracts,
            "currency": "PLN",
        }
        for point in trend.data.months
    ]
    top_clients = [
        {
            "client_id": row.client_id,
            "client_name": row.client_name,
            "contracts_count": row.active_contracts,
            "revenue": row.totals.revenue,
            "margin": row.totals.margin,
            "currency": "PLN",
        }
        for row in clients.data.clients[:10]
    ]

    result_data = {
        "total_revenue": summary.data.totals.revenue,
        "total_margin": summary.data.totals.margin,
        "active_consultants": summary.data.active_contracts,
        "new_contracts_this_month": new_this_month,
        "ending_contracts_30days": ending_contracts_30days,
        "mrr_trend": mrr_trend,
        "top_clients": top_clients,
        "currency": "PLN",
        "quality": summary.quality_status.value,
        "warnings": list(summary.warnings),
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
    period_end: Optional[datetime] = None,
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
    if period_end is not None:
        jobs_q = jobs_q.where(Job.created_at < period_end)
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

    # 2. Placements per DL: first `hired` per candidate x job in the period.
    first_hired = _first_milestone_subquery(PipelineStage.hired)
    placements_q = (
        select(
            Job.id.label("job_id"),
            Job.delivery_lead_id,
            Job.client_id,
            func.count().label("cnt"),
        )
        .join(first_hired, first_hired.c.job_id == Job.id)
        .where(
            Job.recruitment_type == RecruitmentType.body_leasing,
        )
        .group_by(Job.id, Job.delivery_lead_id, Job.client_id)
    )
    if period_start is not None:
        placements_q = placements_q.where(first_hired.c.reached_at >= period_start)
    if period_end is not None:
        placements_q = placements_q.where(first_hired.c.reached_at < period_end)
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
            select(first_hired.c.job_id, func.count().label("cnt"))
            .where(first_hired.c.job_id.in_(open_job_ids))
            .group_by(first_hired.c.job_id)
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

    return per_dl_out, _summarize_dl_rows(per_dl_out)


def _summarize_dl_rows(per_dl_out: list[dict]) -> dict:
    """Recompute totals after applying a caller's row scope."""

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

    return {
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


_DeliveryReportViewer = Annotated[
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


@router.get("/delivery-leads")
async def report_delivery_leads(
    current_user: _DeliveryReportViewer,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """Delivery Lead performance: requests, vacancies, placements, hit ratio,
    fill rate, open pipeline. Dotyczy wyłącznie Jobów `body_leasing`.

    Cached for 5 minutes.
    """
    visible_ids = await delivery_lead_scope(db, user=current_user)
    scope_key = (
        "organization"
        if visible_ids is None
        else ",".join(str(value) for value in sorted(visible_ids)) or "none"
    )
    cache_key = f"reports:delivery_leads:v2:{period}:{scope_key}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached
    start = _period_start(period)

    per_dl, overall = await _compute_dl_metrics(db, period_start=start)
    if visible_ids is not None:
        per_dl = [row for row in per_dl if row["user_id"] in visible_ids]
        overall = _summarize_dl_rows(per_dl)
    result_data = {"period": period, "per_dl": per_dl, "overall": overall}
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


@router.get("/delivery-leads/{dl_id}/trend")
async def report_delivery_lead_trend(
    dl_id: int,
    current_user: _DeliveryReportViewer,
    db: AsyncSession = Depends(get_db),
    months: int = Query(6, ge=1, le=24),
):
    """Trend miesiąc-po-miesiącu dla konkretnego DL. 6M default, max 24M."""
    visible_ids = await delivery_lead_scope(db, user=current_user)
    if visible_ids is not None and dl_id not in visible_ids:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Delivery analytics are limited to the assigned team",
        )
    today = datetime.now(WARSAW).date()
    trend: list[dict] = []
    for i in range(months - 1, -1, -1):
        # Punkt startowy miesiąca (safe month arithmetic).
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        month_start_local = datetime(year, month, 1, tzinfo=WARSAW)
        if month == 12:
            month_end_local = datetime(year + 1, 1, 1, tzinfo=WARSAW)
        else:
            month_end_local = datetime(year, month + 1, 1, tzinfo=WARSAW)
        month_start = month_start_local.astimezone(timezone.utc)
        month_end = month_end_local.astimezone(timezone.utc)

        # Snapshot dla okresu miesiąca — używamy period_start = month_start
        # i filtrujemy by `< month_end` przez tymczasowe wybranie z metrics.
        # Prościej: request/placement w okresie [month_start, month_end).
        per_dl_rows, _ = await _compute_dl_metrics(
            db,
            period_start=month_start,
            period_end=month_end,
            only_dl_id=dl_id,
        )
        row = per_dl_rows[0] if per_dl_rows else None
        requests = row["total_requests"] if row else 0
        vacancies = row["total_vacancies"] if row else 0
        placements = row["placements"] if row else 0
        trend.append(
            {
                "month": month_start_local.strftime("%Y-%m"),
                "month_label": month_start_local.strftime("%b %Y"),
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
    if not current_user.has_any_role(UserRole.delivery_lead):
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
        "leaderboard_top5": [],
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

    # 2. First hired milestone for each candidate x closed job.
    if closed_job_ids:
        first_hired = _first_milestone_subquery(PipelineStage.hired)
        hired_q = (
            select(
                Job.client_id,
                Job.id.label("job_id"),
                func.count().label("cnt"),
            )
            .join(first_hired, first_hired.c.job_id == Job.id)
            .where(Job.id.in_(closed_job_ids))
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

    return per_client_out, _summarize_client_rows(per_client_out)


def _summarize_client_rows(per_client_out: list[dict]) -> dict:
    """Recompute client totals after applying assignment scope."""

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

    return {
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
    visible_client_ids = await operations_client_scope(db, user=current_user)
    scope_key = (
        "organization"
        if visible_client_ids is None
        else ",".join(str(value) for value in sorted(visible_client_ids)) or "none"
    )
    cache_key = (
        f"reports:clients:{period}:{min_closed}:{sort}:"
        f"{exclude_reasons or ''}:{scope_key}"
    )
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    start = _period_start(period) if period != "all" else None
    excluded = _parse_exclude_reasons(exclude_reasons)
    per_client_all, overall = await _compute_client_hit_ratio(
        db, period_start=start, exclude_reasons=excluded
    )
    if visible_client_ids is not None:
        per_client_all = [
            row for row in per_client_all if row["client_id"] in visible_client_ids
        ]
        overall = _summarize_client_rows(per_client_all)
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
    visible_client_ids = await operations_client_scope(db, user=current_user)
    scope_key = (
        "organization"
        if visible_client_ids is None
        else ",".join(str(value) for value in sorted(visible_client_ids)) or "none"
    )
    cache_key = f"reports:clients:at_risk:{period}:{drop_pp}:{min_closed}:{scope_key}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    now_warsaw = datetime.now(WARSAW)
    kind = AnalyticsPeriodKind(period)
    current_period = resolve_period(kind, now=now_warsaw)
    current_start = current_period.start
    current_end = current_period.end
    current_local = current_start.astimezone(WARSAW)
    if kind is AnalyticsPeriodKind.month:
        if current_local.month == 1:
            prev_start_local = current_local.replace(
                year=current_local.year - 1, month=12
            )
        else:
            prev_start_local = current_local.replace(month=current_local.month - 1)
    elif kind is AnalyticsPeriodKind.quarter:
        previous_absolute_month = current_local.year * 12 + current_local.month - 4
        prev_year, prev_month_zero = divmod(previous_absolute_month, 12)
        prev_start_local = current_local.replace(
            year=prev_year, month=prev_month_zero + 1
        )
    else:
        prev_start_local = current_local.replace(year=current_local.year - 1)
    prev_start = prev_start_local.astimezone(timezone.utc)
    prev_end = current_start

    current_rows, _ = await _compute_client_hit_ratio(
        db, period_start=current_start, period_end=current_end
    )
    prev_rows, _ = await _compute_client_hit_ratio(
        db, period_start=prev_start, period_end=prev_end
    )
    if visible_client_ids is not None:
        current_rows = [
            row for row in current_rows if row["client_id"] in visible_client_ids
        ]
        prev_rows = [row for row in prev_rows if row["client_id"] in visible_client_ids]
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
    await require_client_scope(
        db,
        user=current_user,
        client_id=client_id,
        finance=False,
    )
    today = datetime.now(WARSAW).date()
    trend: list[dict] = []
    for i in range(months - 1, -1, -1):
        year = today.year
        month = today.month - i
        while month <= 0:
            month += 12
            year -= 1
        month_start_local = datetime(year, month, 1, tzinfo=WARSAW)
        if month == 12:
            month_end_local = datetime(year + 1, 1, 1, tzinfo=WARSAW)
        else:
            month_end_local = datetime(year, month + 1, 1, tzinfo=WARSAW)
        month_start = month_start_local.astimezone(timezone.utc)
        month_end = month_end_local.astimezone(timezone.utc)

        rows, _ = await _compute_client_hit_ratio(
            db,
            period_start=month_start,
            period_end=month_end,
            only_client_id=client_id,
        )
        row = rows[0] if rows else None
        trend.append(
            {
                "month": month_start_local.strftime("%Y-%m"),
                "month_label": month_start_local.strftime("%b %Y"),
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
    current_user: TacPlus,
    db: AsyncSession = Depends(get_db),
    period: str = Query("year", enum=["week", "month", "quarter", "year"]),
):
    """
    Tenders (przetargi) report: total, won, lost, pending, win rate.
    Cached for 5 minutes.
    """
    can_view_financials = current_user.has_any_role(
        UserRole.admin, UserRole.delivery_lead
    )
    visible_client_ids = await tender_client_scope(db, user=current_user)
    scope_key = (
        "organization"
        if visible_client_ids is None
        else ",".join(str(value) for value in sorted(visible_client_ids)) or "none"
    )
    cache_scope = "finance" if can_view_financials else "operations_redacted"
    cache_key = f"reports:tenders:{period}:{cache_scope}:{scope_key}"
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
    if visible_client_ids is not None:
        tenders_q = tenders_q.where(Job.client_id.in_(visible_client_ids))
    tenders_rows = (await db.execute(tenders_q)).all()

    total = len(tenders_rows)
    lost_list = []
    won_list = []
    pending_list = []
    unknown_list = []
    for r in tenders_rows:
        j = r.Job
        value = (j.salary_max or j.salary_min or 0) if can_view_financials else 0
        entry = {
            "job_id": j.id,
            "job_title": j.title,
            "client": r.client_name or "—",
            "status": j.status.value,
            "value": value,
            "value_redacted": not can_view_financials,
            "deadline": str(j.deadline) if j.deadline else None,
        }
        if j.status.value == "closed":
            if j.close_reason == JobCloseReason.filled_by_us:
                entry["result"] = "wygrana"
                won_list.append(entry)
            elif j.close_reason is not None:
                entry["result"] = "przegrana"
                lost_list.append(entry)
            else:
                entry["result"] = "nieznany"
                unknown_list.append(entry)
        else:
            entry["result"] = "w_toku"
            pending_list.append(entry)

    won_count = len(won_list)
    lost_count = len(lost_list)
    pending_count = len(pending_list)
    unknown_count = len(unknown_list)
    win_rate = _safe_pct(won_count, won_count + lost_count)

    per_tender = won_list + lost_list + unknown_list + pending_list

    result_data = {
        "period": period,
        "total_tenders": total,
        "won": won_count,
        "lost": lost_count,
        "pending": pending_count,
        "unknown": unknown_count,
        "win_rate": win_rate,
        "per_tender": per_tender,
    }
    await cache_set(cache_key, result_data, ttl_seconds=300)
    return result_data


# ── Board Report (Rada Nadzorcza) ──────────────────────────────────────────────


@router.get("/board")
async def report_board(
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

    now_warsaw = datetime.now(WARSAW)
    now_utc = now_warsaw.astimezone(timezone.utc)
    today = now_warsaw.date()
    year_start_date = today.replace(month=1, day=1)
    year_start = datetime(year_start_date.year, 1, 1, tzinfo=WARSAW).astimezone(
        timezone.utc
    )
    year_period = resolve_period(AnalyticsPeriodKind.year, now=now_warsaw)
    manager = AnalyticsManagerService(db)
    finance_summary = await manager.finance_summary(
        year_period, generated_at=now_warsaw
    )
    finance_trend = await manager.finance_trend(year_period)

    # ── Recruitment YTD ──────────────────────────────────────────────────────
    first_hired = _first_milestone_subquery(PipelineStage.hired)
    placements_ytd = (
        await db.execute(
            select(func.count())
            .select_from(first_hired)
            .where(
                first_hired.c.reached_at >= year_start,
                first_hired.c.reached_at < now_utc,
            )
        )
    ).scalar() or 0

    first_verified = _first_milestone_subquery(PipelineStage.verified)
    weryfikacje_ytd = (
        await db.execute(
            select(func.count())
            .select_from(first_verified)
            .where(
                first_verified.c.reached_at >= year_start,
                first_verified.c.reached_at < now_utc,
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
    revenue_ytd = finance_summary.data.totals.revenue
    margin_ytd = finance_summary.data.totals.margin
    active_consultants = finance_summary.data.active_contracts

    # ── Delivery ─────────────────────────────────────────────────────────────
    dl_rows, dl_overall = await _compute_dl_metrics(
        db,
        period_start=year_start,
        period_end=now_utc,
    )
    top_dl = dl_rows[0]["name"] if dl_rows else "—"
    avg_hit_ratio = dl_overall["avg_hit_ratio"]

    # ── Tenders ──────────────────────────────────────────────────────────────
    tenders_total = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.recruitment_type == RecruitmentType.tender,
                Job.created_at >= year_start,
                Job.created_at < now_utc,
            )
        )
    ).scalar() or 0
    tenders_won = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.recruitment_type == RecruitmentType.tender,
                Job.status == "closed",
                Job.close_reason == JobCloseReason.filled_by_us,
                Job.created_at >= year_start,
                Job.created_at < now_utc,
            )
        )
    ).scalar() or 0
    tenders_resolved = (
        await db.execute(
            select(func.count(Job.id)).where(
                Job.recruitment_type == RecruitmentType.tender,
                Job.status == "closed",
                Job.close_reason.is_not(None),
                Job.created_at >= year_start,
                Job.created_at < now_utc,
            )
        )
    ).scalar() or 0
    tender_win_rate = _safe_pct(tenders_won, tenders_resolved)

    # ── Headcount ────────────────────────────────────────────────────────────
    total_users = (await db.execute(select(func.count(User.id)))).scalar() or 0
    total_candidates = (
        await db.execute(select(func.count(Candidate.id)))
    ).scalar() or 0

    # ── 12-month Trends ───────────────────────────────────────────────────────
    finance_by_month = {point.month: point for point in finance_trend.data.months}
    trends = []
    for i in range(11, -1, -1):
        absolute_month = today.year * 12 + (today.month - 1) - i
        month_year, month_index = divmod(absolute_month, 12)
        month_start_date = date(month_year, month_index + 1, 1)
        if month_start_date.month == 12:
            month_end_date = month_start_date.replace(
                year=month_start_date.year + 1, month=1, day=1
            )
        else:
            month_end_date = month_start_date.replace(
                month=month_start_date.month + 1, day=1
            )
        month_start = datetime.combine(
            month_start_date, datetime.min.time(), tzinfo=WARSAW
        ).astimezone(timezone.utc)
        month_end = datetime.combine(
            month_end_date, datetime.min.time(), tzinfo=WARSAW
        ).astimezone(timezone.utc)

        m_placements = (
            await db.execute(
                select(func.count())
                .select_from(first_hired)
                .where(
                    first_hired.c.reached_at >= month_start,
                    first_hired.c.reached_at < month_end,
                )
            )
        ).scalar() or 0

        finance_point = finance_by_month.get(month_start_date.strftime("%Y-%m"))

        trends.append(
            {
                "month": month_start.strftime("%Y-%m"),
                "month_label": month_start_date.strftime("%b %Y"),
                "placements": m_placements,
                "revenue": (finance_point.totals.revenue if finance_point else None),
                "consultants": (finance_point.active_contracts if finance_point else 0),
                "currency": "PLN",
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
            "currency": "PLN",
            "quality": finance_summary.quality_status.value,
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
        "quality": finance_summary.quality_status.value,
        "warnings": list(finance_summary.warnings),
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

POWER_CALLING_WORKDAYS = 5


def _iso_week_bounds(
    offset_weeks: int = 1,
) -> tuple[datetime, datetime, int, int]:
    """Zwraca (start_utc, end_utc_exclusive, iso_week, iso_year) dla tygodnia
    sprzed `offset_weeks` (1 = poprzedni tydzień). Granice są lokalnymi
    północami Europe/Warsaw i tworzą przedział `[start, end)`."""
    now = datetime.now(WARSAW)
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
    """Weekly calls and verification pace as two independent KPIs.

    Power Calling means completed CloudTalk calls. Verifications use the first
    canonical ``verified`` milestone and its canonical attribution.
    """
    start, end, iso_week, iso_year = _iso_week_bounds(offset_weeks)
    canonical_period = AnalyticsPeriod(
        kind=AnalyticsPeriodKind.custom,
        start=start,
        end=end,
    )
    calls_available = bool(
        settings.CLOUDTALK_ENABLED
        and settings.CLOUDTALK_API_KEY_ID
        and settings.CLOUDTALK_API_KEY_SECRET
        and settings.CLOUDTALK_WEBHOOK_SECRET
    )
    rows = (
        await AnalyticsV1Service(db).team_kpis(
            canonical_period, calls_available=calls_available
        )
    ).users

    # Competence category per user (primary).
    user_ids = [r.user_id for r in rows]
    cat_map: dict[int, dict] = {}
    role_map: dict[int, str] = {}
    if user_ids:
        role_rows = await db.execute(
            select(User.id, User.role).where(User.id.in_(user_ids))
        )
        role_map = {
            user_id: role.value if hasattr(role, "value") else str(role)
            for user_id, role in role_rows
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
        calls_per_day = (
            round(r.calls_completed / POWER_CALLING_WORKDAYS, 2)
            if r.calls_completed is not None
            else None
        )
        verifications_per_day = round(r.verifications / POWER_CALLING_WORKDAYS, 2)
        meets_calls = (
            calls_per_day >= settings.POWERCALLING_DAILY_TARGET
            if calls_per_day is not None
            else None
        )
        meets_verifications = (
            verifications_per_day >= settings.VERIFICATIONS_DAILY_TARGET
        )
        entries.append(
            {
                "user_id": r.user_id,
                "name": r.user_name,
                "role": role_map.get(r.user_id, "recruiter"),
                "primary_category": cat_map.get(r.user_id),
                "calls_week": r.calls_completed,
                "calls_per_day": calls_per_day,
                "verifications_week": r.verifications,
                "verifications_per_day": verifications_per_day,
                # One-release compatibility aliases now use the real Power
                # Calling definition (completed calls).
                "per_day": calls_per_day,
                "workdays": POWER_CALLING_WORKDAYS,
                "meets_call_target": meets_calls,
                "meets_verification_target": meets_verifications,
                "meets_target": meets_calls,
                "progress_pct": (
                    min(
                        100,
                        round(
                            (calls_per_day / settings.POWERCALLING_DAILY_TARGET) * 100,
                            0,
                        ),
                    )
                    if calls_per_day is not None and settings.POWERCALLING_DAILY_TARGET
                    else None
                ),
            }
        )

    return {
        "week_label": f"Tydz. {iso_week}/{iso_year}",
        "iso_week": iso_week,
        "iso_year": iso_year,
        "date_from": start.date().isoformat(),
        "date_to": (end - timedelta(days=1)).date().isoformat(),
        "target_per_day": settings.POWERCALLING_DAILY_TARGET,
        "call_target_per_day": settings.POWERCALLING_DAILY_TARGET,
        "verification_target_per_day": settings.VERIFICATIONS_DAILY_TARGET,
        "calls_available": calls_available,
        "calls_quality": "complete" if calls_available else "unavailable",
        "workdays": POWER_CALLING_WORKDAYS,
        "requirement_text": (
            f"Cele: {settings.POWERCALLING_DAILY_TARGET} zakończonych rozmów i "
            f"{settings.VERIFICATIONS_DAILY_TARGET} weryfikacje / dzień roboczy"
        ),
        "entries": entries,
        "meets_target_count": (
            sum(1 for e in entries if e["meets_target"]) if calls_available else None
        ),
        "total_count": len(entries),
    }
