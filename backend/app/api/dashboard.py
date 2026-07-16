from datetime import date

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import (
    AnalyticsCapability,
    user_has_capability,
)
from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.contract import Contract, ContractStatus
from app.models.recruitment_pipeline import CandidateStage, PipelineStage
from app.models.activity import Activity
from app.models.user import User
from app.models.user_activity import UserActivity, UserActionType
from app.api.deps import CurrentUser, OperationalUser
from app.services.dashboard_metrics import compute_kpi_snapshot

router = APIRouter()


@router.get("/stats")
async def get_stats(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Main KPI dashboard stats. Shared SQL aggregation with /api/admin/snapshot."""
    return await compute_kpi_snapshot(db)


@router.get("/kpis")
async def get_kpis(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """ATS KPI counts + (dla uprawnionych) miesięczny ranking rekruterów.

    R0 (plan 2026-07-16): InfraReporter wycięty — zewnętrzny serwis z
    hardcoded API key nie jest źródłem statystyk NEXUS-a. Imienny ranking
    ``top_recruiters`` widzą tylko role z VIEW_RECRUITMENT_RANKING; rola
    ``user`` dostaje wyłącznie agregaty. Cache jest rozdzielony per wariant
    odpowiedzi, żeby viewer nigdy nie dostał wersji z rankingiem.
    GET /api/dashboard/kpis
    """
    include_ranking = user_has_capability(
        current_user, AnalyticsCapability.VIEW_RECRUITMENT_RANKING
    )
    cache_key = f"dashboard:kpis:{'ranking' if include_ranking else 'aggregates'}"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

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

    top_recruiters: list[dict] = []
    if include_ranking:
        # Top recruiters this month (from user activities)
        from sqlalchemy import case

        leaderboard_result = await db.execute(
            select(
                User.id,
                User.name,
                func.count(UserActivity.id).label("total_actions"),
                func.sum(
                    case(
                        (
                            UserActivity.action_type == UserActionType.placement_closed,
                            1,
                        ),
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
    }
    await cache_set(cache_key, result_data, ttl_seconds=120)  # cache 2 min
    return result_data


@router.get("/recent-activity")
async def recent_activity(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = 20,
):
    """Recent activity feed for dashboard.

    R0: feed zawiera surowe ``details`` (nazwiska kandydatów, nazwy klientów,
    e-maile) — to nie są „bezpieczne agregaty", więc rola ``user`` (read-only
    viewer) nie ma tu wstępu. Guard = OperationalUser.
    """
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
