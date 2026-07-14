from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.cache import cache_get, cache_set
from app.models.recruitment_pipeline import CandidateStage
from app.models.activity import Activity
from app.models.user import User, UserRole
from app.api.deps import CurrentUser
from app.analytics.periods import AnalyticsPeriodKind, resolve_period
from app.analytics.schemas import METRIC_VERSION
from app.services.analytics_v1 import AnalyticsV1Service
from app.services.dashboard_metrics import compute_kpi_snapshot

router = APIRouter()


def _is_viewer_only(user: User) -> bool:
    """Internal viewer has aggregate-only access unless it holds another role."""
    return user.get_all_roles() == {UserRole.user}


@router.get("/stats")
async def get_stats(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """Main KPI dashboard stats. Shared SQL aggregation with /api/admin/snapshot."""
    return await compute_kpi_snapshot(db)


@router.get("/kpis")
async def get_kpis(current_user: CurrentUser, db: AsyncSession = Depends(get_db)):
    """
    Legacy dashboard adapter backed exclusively by canonical live ATS metrics.
    Cached for 2 minutes.
    GET /api/dashboard/kpis
    """
    snapshot = await compute_kpi_snapshot(db)
    month = resolve_period(AnalyticsPeriodKind.month)
    team = await AnalyticsV1Service(db).team_kpis(month)
    candidates_added = sum(row.candidates_added for row in team.users)

    if _is_viewer_only(current_user):
        return {
            "ats": {
                "active_consultants": snapshot["contracts"]["active"],
                "placements_this_month": snapshot["pipeline"]["hired_this_month"],
                "candidates_added_this_month": candidates_added,
                "top_recruiters": [],
            },
            "infrareporter": None,
            "infrareporter_available": False,
            "metric_version": METRIC_VERSION,
            "scope": "organization_redacted",
        }

    cache_key = "dashboard:kpis"
    cached = await cache_get(cache_key)
    if cached is not None:
        return cached

    # Compatibility shape, but every value comes from canonical calls,
    # candidates and first milestones rather than UserActivity.
    top_recruiters = [
        {
            "user_id": row.user_id,
            "user_name": row.user_name,
            "total_actions": (
                row.calls_completed
                + row.verifications
                + row.candidates_added
                + row.recommendations
                + row.placements
            ),
            "placements": row.placements,
        }
        for row in team.users[:5]
    ]

    result_data = {
        "ats": {
            "active_consultants": snapshot["contracts"]["active"],
            "placements_this_month": snapshot["pipeline"]["hired_this_month"],
            "candidates_added_this_month": candidates_added,
            "top_recruiters": top_recruiters,
        },
        "infrareporter": None,
        "infrareporter_available": False,
        "metric_version": METRIC_VERSION,
        "scope": "recruitment_team",
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
    if _is_viewer_only(current_user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Viewer accounts can access aggregate statistics only",
        )
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
    """Current pipeline snapshot: latest stage per candidate/job pair."""
    ranked = select(
        CandidateStage.stage.label("stage"),
        func.row_number()
        .over(
            partition_by=(CandidateStage.candidate_id, CandidateStage.job_id),
            order_by=(CandidateStage.moved_at.desc(), CandidateStage.id.desc()),
        )
        .label("stage_rank"),
    ).subquery()
    result = await db.execute(
        select(ranked.c.stage, func.count())
        .where(ranked.c.stage_rank == 1)
        .group_by(ranked.c.stage)
    )
    return {stage.value: count for stage, count in result.all()}
