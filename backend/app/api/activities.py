"""
User Activity Tracking API.
Endpoints for stats and leaderboard based on UserActivity records.
Also provides a combined activity feed for the dashboard.
"""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.models.user_activity import UserActivity, UserActionType
from app.models.activity import Activity
from app.analytics.capabilities import AnalyticsCapability
from app.analytics.periods import AnalyticsPeriodKind, resolve_period
from app.api.deps import require_analytics_capabilities
from app.core.config import settings
from app.services.analytics_v1 import AnalyticsV1Service

router = APIRouter()

ActivityViewer = Annotated[
    User,
    Depends(require_analytics_capabilities(AnalyticsCapability.view_recruitment_team)),
]


def _period_start(period: str) -> datetime:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "week":
        return now - timedelta(days=7)
    elif period == "month":
        return now - timedelta(days=30)
    elif period == "quarter":
        return now - timedelta(days=90)
    else:
        return now - timedelta(days=30)


@router.get("/stats")
async def get_activity_stats(
    current_user: ActivityViewer,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(None),
    period: str = Query("week", pattern="^(today|week|month|quarter)$"),
):
    """
    Returns counts per action type for a specific user or all users.
    GET /api/activities/stats?user_id=X&period=week
    """
    since = _period_start(period)
    query = select(
        UserActivity.action_type,
        func.count(UserActivity.id).label("count"),
    ).where(UserActivity.created_at >= since)

    if user_id:
        query = query.where(UserActivity.user_id == user_id)

    query = query.group_by(UserActivity.action_type)
    result = await db.execute(query)
    rows = result.all()

    stats = {action_type.value: 0 for action_type in UserActionType}
    for action_type, count in rows:
        stats[action_type.value] = count

    return {
        "period": period,
        "user_id": user_id,
        "since": since.isoformat(),
        "stats": stats,
    }


@router.get("/leaderboard")
async def get_leaderboard(
    current_user: ActivityViewer,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(today|week|month|quarter)$"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Top performers ranking based on activity counts.
    GET /api/activities/leaderboard?period=month
    """
    kind = {
        "today": AnalyticsPeriodKind.day,
        "week": AnalyticsPeriodKind.week,
        "month": AnalyticsPeriodKind.month,
        "quarter": AnalyticsPeriodKind.quarter,
    }[period]
    analytics_period = resolve_period(kind)
    calls_available = bool(
        settings.CLOUDTALK_ENABLED
        and settings.CLOUDTALK_API_KEY_ID
        and settings.CLOUDTALK_API_KEY_SECRET
        and settings.CLOUDTALK_WEBHOOK_SECRET
    )
    rows = (
        await AnalyticsV1Service(db).team_kpis(
            analytics_period, calls_available=calls_available
        )
    ).users

    leaderboard = []
    for rank, row in enumerate(rows[:limit], start=1):
        total_actions = (
            (row.calls_completed or 0)
            + row.verifications
            + row.candidates_added
            + row.recommendations
            + row.placements
        )
        leaderboard.append(
            {
                "rank": rank,
                "user_id": row.user_id,
                "user_name": row.user_name,
                "candidates_added": row.candidates_added,
                "screenings": row.verifications,
                "recommendations": row.recommendations,
                "interviews": None,
                "placements": row.placements,
                "calls": row.calls_completed,
                "calls_available": row.calls_available,
                "total_actions": total_actions,
            }
        )

    return {
        "period": period,
        "since": analytics_period.start.isoformat(),
        "until": analytics_period.end.isoformat(),
        "metric_source": "analytics_v1",
        "leaderboard": leaderboard,
    }


# ── Human-readable action labels (Polish) ────────────────────────────────────

_ACTION_LABELS_PL: dict = {
    "created": "dodał(a)",
    "updated": "zaktualizował(a)",
    "deleted": "usunął(a)",
    "imported": "zaimportował(a)",
    "stage_changed": "zmienił(a) etap",
    "cv_uploaded": "wgrał(a) CV",
    "hired": "zatrudnił(a)",
    "candidate_added": "dodał(a) kandydata",
    "screening_done": "przeprowadził(a) screening",
    "interview_scheduled": "umówił(a) rozmowę",
    "placement_closed": "zamknął(a) placement",
    "call_made": "wykonał(a) rozmowę",
    "note_added": "dodał(a) notatkę",
}

_ENTITY_LABELS_PL: dict = {
    "candidate": "kandydata",
    "job": "ofertę",
    "client": "klienta",
    "contract": "kontrakt",
    "note": "notatkę",
    "pipeline": "pipeline",
}


def _build_description(action: str, entity_type: str, entity_name: str) -> str:
    verb = _ACTION_LABELS_PL.get(action, action)
    entity_label = _ENTITY_LABELS_PL.get(entity_type, entity_type)
    return f"{verb} {entity_label} {entity_name}".strip()


def _entity_link(entity_type: str, entity_id: int) -> Optional[str]:
    links = {
        "candidate": f"/candidates?id={entity_id}",
        "job": f"/jobs/{entity_id}",
        "client": f"/clients/{entity_id}",
        "contract": "/contracts",
    }
    return links.get(entity_type)


@router.get("/feed")
async def get_activity_feed(
    current_user: ActivityViewer,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Combined feed of all recent system activities.
    Returns last N activities across all entity types with Polish descriptions.
    GET /api/activities/feed
    """
    # Load activities with user join
    query = (
        select(Activity, User.name.label("user_name"))
        .outerjoin(User, Activity.user_id == User.id)
        .order_by(desc(Activity.created_at))
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    feed = []
    for activity, user_name in rows:
        details = activity.details or {}
        entity_name = details.get("name", details.get("title", ""))

        feed.append(
            {
                "id": activity.id,
                "user": user_name or "System",
                "user_id": activity.user_id,
                "action": activity.action,
                "entity_type": activity.entity_type,
                "entity_id": activity.entity_id,
                "entity_name": entity_name,
                "description": _build_description(
                    activity.action,
                    activity.entity_type,
                    entity_name,
                ),
                "full_text": f"{user_name or 'System'} {_build_description(activity.action, activity.entity_type, entity_name)}".strip(),
                "timestamp": activity.created_at.isoformat()
                if activity.created_at
                else None,
                "link": _entity_link(activity.entity_type, activity.entity_id),
                "details": details,
            }
        )

    return feed
