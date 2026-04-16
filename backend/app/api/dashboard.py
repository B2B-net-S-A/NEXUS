from datetime import date, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.candidate import Candidate, CandidateStatus
from app.models.job import Job, JobStatus
from app.models.client import Client
from app.models.contract import Contract, ContractStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.activity import Activity
from app.models.user import User
from app.models.user_activity import UserActivity, UserActionType
from app.api.deps import CurrentUser
from app.services import infrareporter

router = APIRouter()


@router.get("/stats")
async def get_stats(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Main KPI dashboard stats."""
    candidates_total = (await db.execute(select(func.count(Candidate.id)))).scalar()
    candidates_active = (
        await db.execute(
            select(func.count(Candidate.id)).where(
                Candidate.status == CandidateStatus.active
            )
        )
    ).scalar()
    jobs_open = (
        await db.execute(
            select(func.count(Job.id)).where(Job.status == JobStatus.published)
        )
    ).scalar()
    clients_active = (await db.execute(select(func.count(Client.id)))).scalar()
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar()

    # Contracts expiring in next 30 days
    cutoff = date.today() + timedelta(days=30)
    contracts_expiring = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.end_date <= cutoff,
                Contract.end_date >= date.today(),
                Contract.status == ContractStatus.active,
            )
        )
    ).scalar()

    # Hired this month
    first_of_month = date.today().replace(day=1)
    hired_this_month = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage == PipelineStage.hired,
                CandidateStage.moved_at >= first_of_month,
            )
        )
    ).scalar()

    return {
        "candidates": {
            "total": candidates_total,
            "active": candidates_active,
        },
        "jobs": {
            "open": jobs_open,
        },
        "clients": {
            "total": clients_active,
        },
        "contracts": {
            "active": contracts_active,
            "expiring_soon": contracts_expiring,
        },
        "pipeline": {
            "hired_this_month": hired_this_month,
        },
    }


@router.get("/kpis")
async def get_kpis(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """
    Merged KPIs: InfraReporter data + ATS stats.
    Cached for 2 minutes.
    GET /api/dashboard/kpis
    """
    cache_key = "dashboard:kpis"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    # Fetch InfraReporter data
    ir_data = await infrareporter.get_infrareporter_kpis()

    # ATS stats
    contracts_active = (
        await db.execute(
            select(func.count(Contract.id)).where(
                Contract.status == ContractStatus.active
            )
        )
    ).scalar()

    first_of_month = date.today().replace(day=1)
    placements_this_month = (
        await db.execute(
            select(func.count(CandidateStage.id)).where(
                CandidateStage.stage == PipelineStage.hired,
                CandidateStage.moved_at >= first_of_month,
            )
        )
    ).scalar()

    candidates_added_this_month = (
        await db.execute(
            select(func.count(UserActivity.id)).where(
                UserActivity.action_type == UserActionType.candidate_added,
                UserActivity.created_at >= first_of_month,
            )
        )
    ).scalar()

    # Top recruiters this month (from user activities)
    from sqlalchemy import case

    leaderboard_result = await db.execute(
        select(
            User.id,
            User.name,
            func.count(UserActivity.id).label("total_actions"),
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.placement_closed, 1),
                    else_=0,
                )
            ).label("placements"),
        )
        .join(UserActivity, User.id == UserActivity.user_id)
        .where(UserActivity.created_at >= first_of_month)
        .group_by(User.id, User.name)
        .order_by(func.count(UserActivity.id).desc())
        .limit(5)
    )
    top_recruiters = [
        {
            "user_id": row.id,
            "user_name": row.name,
            "total_actions": row.total_actions,
            "placements": row.placements,
        }
        for row in leaderboard_result.all()
    ]

    result_data = {
        "ats": {
            "active_consultants": contracts_active,
            "placements_this_month": placements_this_month,
            "candidates_added_this_month": candidates_added_this_month,
            "top_recruiters": top_recruiters,
        },
        "infrareporter": ir_data,
        "infrareporter_available": ir_data is not None,
    }
    await cache_set(cache_key, result_data, ttl_seconds=120)  # cache 2 min
    return result_data


@router.get("/recent-activity")
async def recent_activity(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Recent activity feed for dashboard."""
    result = await db.execute(
        select(Activity).order_by(Activity.created_at.desc()).limit(limit)
    )
    activities = result.scalars().all()
    return [
        {
            "id": a.id,
            "entity_type": a.entity_type,
            "entity_id": a.entity_id,
            "action": a.action,
            "user_id": a.user_id,
            "details": a.details,
            "created_at": a.created_at,
        }
        for a in activities
    ]


@router.get("/pipeline-funnel")
async def pipeline_funnel(
    current_user: CurrentUser, db: AsyncSession = Depends(get_db)
):
    """Aggregate pipeline counts per stage across all jobs."""
    result = await db.execute(
        select(CandidateStage.stage, func.count(CandidateStage.id)).group_by(
            CandidateStage.stage
        )
    )
    return {stage.value: count for stage, count in result.all()}
