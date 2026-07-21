"""
User Activity Tracking API.
Endpoints for stats and leaderboard based on UserActivity records.
Also provides a combined activity feed for the dashboard.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import case, func, select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.models.user import User
from app.models.user_activity import UserActivity, UserActionType
from app.models.activity import Activity
from app.api.deps import CurrentUser, OperationalUser
from app.api.financial_access import has_financial_access, redact_feed_activity
from app.analytics.capabilities import (
    AnalyticsCapability,
    require_capability,
    user_has_capability,
)

router = APIRouter()


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
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    user_id: Optional[int] = Query(None),
    period: str = Query("week", pattern="^(today|week|month|quarter)$"),
):
    """
    Returns counts per action type for a specific user or all users.
    GET /api/activities/stats?user_id=X&period=week

    R0 (plan 2026-07-16): statystyki INNEGO usera wymagają VIEW_TEAM_KPI —
    wcześniej dowolny zalogowany mógł odpytać dowolnego usera (IDOR).
    """
    if (
        user_id is not None
        and user_id != current_user.id
        and not user_has_capability(current_user, AnalyticsCapability.VIEW_TEAM_KPI)
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Statystyki innego użytkownika wymagają uprawnień zespołowych",
        )
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
    # R0: imienny ranking = VIEW_RECRUITMENT_RANKING (rola `user` odpada).
    current_user: User = Depends(
        require_capability(AnalyticsCapability.VIEW_RECRUITMENT_RANKING)
    ),
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", pattern="^(today|week|month|quarter)$"),
    limit: int = Query(10, ge=1, le=50),
):
    """
    Top performers ranking based on activity counts.
    GET /api/activities/leaderboard?period=month
    """
    since = _period_start(period)

    # Aggregate per user and action type
    subq = (
        select(
            UserActivity.user_id,
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.candidate_added, 1),
                    else_=0,
                )
            ).label("candidates_added"),
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.screening_done, 1),
                    else_=0,
                )
            ).label("screenings"),
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.interview_scheduled, 1),
                    else_=0,
                )
            ).label("interviews"),
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.placement_closed, 1),
                    else_=0,
                )
            ).label("placements"),
            func.sum(
                case(
                    (UserActivity.action_type == UserActionType.call_made, 1),
                    else_=0,
                )
            ).label("calls"),
            func.count(UserActivity.id).label("total_actions"),
        )
        .where(UserActivity.created_at >= since)
        .group_by(UserActivity.user_id)
        .subquery()
    )

    query = (
        select(User.id, User.name, User.email, subq)
        .join(subq, User.id == subq.c.user_id)
        .order_by(subq.c.total_actions.desc())
        .limit(limit)
    )
    result = await db.execute(query)
    rows = result.all()

    leaderboard = []
    for rank, row in enumerate(rows, start=1):
        leaderboard.append(
            {
                "rank": rank,
                "user_id": row.id,
                "user_name": row.name,
                "candidates_added": row.candidates_added,
                "screenings": row.screenings,
                "interviews": row.interviews,
                "placements": row.placements,
                "calls": row.calls,
                "total_actions": row.total_actions,
            }
        )

    return {
        "period": period,
        "since": since.isoformat(),
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
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
):
    """
    Combined feed of all recent system activities.
    Returns last N activities across all entity types with Polish descriptions.
    GET /api/activities/feed

    R0: feed niesie nazwiska kandydatów / nazwy klientów w ``entity_name``
    i surowe ``details`` — nie dla roli ``user`` (guard OperationalUser).
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

    # Finance protection (P1): the raw ``details`` can carry rate amounts
    # (candidate ``client_rate_changed`` audit, contract ``updated`` events).
    # Non-finance readers get rate-change rows omitted + finance keys stripped,
    # exactly as the candidate timeline redacts them.
    finance_ok = has_financial_access(current_user)

    feed = []
    for activity, user_name in rows:
        details = redact_feed_activity(
            activity.action, activity.details or {}, finance_ok=finance_ok
        )
        if details is None:
            continue
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
