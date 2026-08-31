"""Router `/api/linkedin-metrics/*` — manual LinkedIn activity tracking.

Źródło danych: bulk-edit adminów (HoR + admin), tabela
`linkedin_daily_metrics`. Dla zalogowanego TAC/sourcera/rekruera — GET
/my-summary (własne dane).
"""

from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, HeadOfRecruitmentPlus, require_roles
from app.core.database import get_db
from app.models.linkedin_metric import LinkedInDailyMetric
from app.models.user import User, UserRole
from app.schemas.linkedin_metric import (
    LinkedInBulkPayload,
    LinkedInMetricOut,
    LinkedInSummary,
    LinkedInUserTotals,
)

router = APIRouter()

LinkedInMetricsReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.finance,
        )
    ),
]


# ── Helpers ─────────────────────────────────────────────────────────────


def _period_bounds(period: str, today: Optional[date] = None) -> tuple[date, date]:
    """Zwraca (from_date_inclusive, to_date_inclusive) dla okresu."""
    today = today or date.today()
    if period == "week":
        start = today - timedelta(days=today.weekday())  # poniedziałek
        end = start + timedelta(days=6)
    elif period == "month":
        start = today.replace(day=1)
        if today.month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
    elif period == "quarter":
        q = (today.month - 1) // 3 + 1
        start = today.replace(month=(q - 1) * 3 + 1, day=1)
        end_month = q * 3
        if end_month == 12:
            end = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
        else:
            end = today.replace(month=end_month + 1, day=1) - timedelta(days=1)
    elif period == "year":
        start = today.replace(month=1, day=1)
        end = today.replace(month=12, day=31)
    else:
        # default: month
        start = today.replace(day=1)
        end = today
    return start, end


def _safe_pct(num: int, denom: int) -> float:
    return round(num / denom * 100, 1) if denom else 0.0


def _week_number_for(d: date) -> int:
    return d.isocalendar().week


# ── List / batch ──────────────────────────────────────────────────────


@router.get("/batch", response_model=list[LinkedInMetricOut])
async def list_batch(
    _user: LinkedInMetricsReadUser,
    db: AsyncSession = Depends(get_db),
    date_from: date = Query(..., description="Inclusive start date"),
    date_to: date = Query(..., description="Inclusive end date"),
    user_ids: Optional[str] = Query(None, description="Comma-separated user IDs"),
):
    """Pobiera wszystkie wiersze w zakresie dat (bulk-edit grid)."""
    q = (
        select(
            LinkedInDailyMetric.id,
            LinkedInDailyMetric.user_id,
            LinkedInDailyMetric.report_date,
            LinkedInDailyMetric.week_number,
            LinkedInDailyMetric.cv_added,
            LinkedInDailyMetric.messages_sent,
            LinkedInDailyMetric.responses_received,
            LinkedInDailyMetric.notes,
            User.name.label("name"),
        )
        .join(User, LinkedInDailyMetric.user_id == User.id)
        .where(
            LinkedInDailyMetric.report_date >= date_from,
            LinkedInDailyMetric.report_date <= date_to,
        )
        .order_by(User.name, LinkedInDailyMetric.report_date)
    )
    if user_ids:
        ids = [int(x) for x in user_ids.split(",") if x.strip().isdigit()]
        if ids:
            q = q.where(LinkedInDailyMetric.user_id.in_(ids))
    rows = (await db.execute(q)).all()
    return [
        LinkedInMetricOut(
            id=r.id,
            user_id=r.user_id,
            name=r.name,
            report_date=r.report_date,
            week_number=r.week_number,
            cv_added=r.cv_added,
            messages_sent=r.messages_sent,
            responses_received=r.responses_received,
            notes=r.notes,
        )
        for r in rows
    ]


@router.get("/users", response_model=list[dict])
async def list_linkedin_users(
    _user: LinkedInMetricsReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista userów uprawnionych do raportowania LinkedIn (TAC/rek/sourcer)."""
    rows = (
        (
            await db.execute(
                select(User)
                .where(
                    User.is_active == True,  # noqa: E712
                    User.role.in_([UserRole.tac, UserRole.recruiter, UserRole.sourcer]),
                )
                .order_by(User.name)
            )
        )
        .scalars()
        .all()
    )
    return [
        {"id": u.id, "name": u.name, "role": u.role.value, "email": u.email}
        for u in rows
    ]


# ── Upsert ─────────────────────────────────────────────────────────────


@router.post("/batch", status_code=status.HTTP_200_OK)
async def upsert_batch(
    payload: LinkedInBulkPayload,
    current_user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    """Bulk upsert (user_id, report_date). Istniejące → update; nowe → insert.

    Payload:
        {"rows": [{"user_id": 1, "report_date": "2026-04-20", "cv_added": 5,
                   "messages_sent": 30, "responses_received": 3}]}
    """
    saved = 0
    for row in payload.rows:
        existing = (
            await db.execute(
                select(LinkedInDailyMetric).where(
                    LinkedInDailyMetric.user_id == row.user_id,
                    LinkedInDailyMetric.report_date == row.report_date,
                )
            )
        ).scalar_one_or_none()
        if existing:
            existing.cv_added = row.cv_added
            existing.messages_sent = row.messages_sent
            existing.responses_received = row.responses_received
            existing.notes = row.notes
            existing.week_number = _week_number_for(row.report_date)
        else:
            db.add(
                LinkedInDailyMetric(
                    user_id=row.user_id,
                    report_date=row.report_date,
                    week_number=_week_number_for(row.report_date),
                    cv_added=row.cv_added,
                    messages_sent=row.messages_sent,
                    responses_received=row.responses_received,
                    notes=row.notes,
                    created_by=current_user.id,
                )
            )
        saved += 1
    await db.commit()
    return {"ok": True, "saved": saved}


@router.delete("/{metric_id}")
async def delete_metric(
    metric_id: int,
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    row = (
        await db.execute(
            select(LinkedInDailyMetric).where(LinkedInDailyMetric.id == metric_id)
        )
    ).scalar_one_or_none()
    if row is None:
        raise HTTPException(404, "Metric not found")
    await db.delete(row)
    await db.commit()
    return {"ok": True}


# ── Summary (team-wide) ────────────────────────────────────────────────


async def compute_summary(
    db: AsyncSession,
    date_from: date,
    date_to: date,
    only_user_id: Optional[int] = None,
) -> tuple[list[LinkedInUserTotals], dict]:
    q = (
        select(
            LinkedInDailyMetric.user_id,
            User.name,
            User.role,
            func.coalesce(func.sum(LinkedInDailyMetric.cv_added), 0).label("cv_added"),
            func.coalesce(func.sum(LinkedInDailyMetric.messages_sent), 0).label(
                "messages_sent"
            ),
            func.coalesce(func.sum(LinkedInDailyMetric.responses_received), 0).label(
                "responses_received"
            ),
            func.count(LinkedInDailyMetric.id).label("days_reported"),
        )
        .join(User, LinkedInDailyMetric.user_id == User.id)
        .where(
            LinkedInDailyMetric.report_date >= date_from,
            LinkedInDailyMetric.report_date <= date_to,
        )
        .group_by(LinkedInDailyMetric.user_id, User.name, User.role)
        .order_by(func.sum(LinkedInDailyMetric.cv_added).desc())
    )
    if only_user_id is not None:
        q = q.where(LinkedInDailyMetric.user_id == only_user_id)
    rows = (await db.execute(q)).all()

    per_user = [
        LinkedInUserTotals(
            user_id=r.user_id,
            name=r.name,
            role=r.role.value if hasattr(r.role, "value") else str(r.role),
            cv_added=int(r.cv_added),
            messages_sent=int(r.messages_sent),
            responses_received=int(r.responses_received),
            response_rate=_safe_pct(int(r.responses_received), int(r.messages_sent)),
            cv_response_rate=_safe_pct(int(r.responses_received), int(r.cv_added)),
            days_reported=int(r.days_reported),
        )
        for r in rows
    ]

    tot_cv = sum(u.cv_added for u in per_user)
    tot_msg = sum(u.messages_sent for u in per_user)
    tot_resp = sum(u.responses_received for u in per_user)
    totals = {
        "cv_added": tot_cv,
        "messages_sent": tot_msg,
        "responses_received": tot_resp,
        "response_rate": _safe_pct(tot_resp, tot_msg),
        "cv_response_rate": _safe_pct(tot_resp, tot_cv),
        "active_users": len(per_user),
    }
    return per_user, totals


@router.get("/summary", response_model=LinkedInSummary)
async def summary(
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """Team-wide aggregacja za okres. Dostępne dla wszystkich zalogowanych."""
    start, end = _period_bounds(period)
    per_user, totals = await compute_summary(db, start, end)
    return LinkedInSummary(
        period=period,
        date_from=start,
        date_to=end,
        per_user=per_user,
        totals=totals,
    )


@router.get("/my-summary")
async def my_summary(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    period: str = Query("month", enum=["week", "month", "quarter", "year"]),
):
    """Własna aggregacja + trend dzienny dla zalogowanego usera."""
    start, end = _period_bounds(period)
    per_user, _totals = await compute_summary(
        db, start, end, only_user_id=current_user.id
    )
    me = per_user[0] if per_user else None

    # Trend dzienny (ostatnie 14 dni).
    trend_start = end - timedelta(days=13)
    trend_rows = (
        await db.execute(
            select(
                LinkedInDailyMetric.report_date,
                LinkedInDailyMetric.cv_added,
                LinkedInDailyMetric.messages_sent,
                LinkedInDailyMetric.responses_received,
            )
            .where(
                LinkedInDailyMetric.user_id == current_user.id,
                LinkedInDailyMetric.report_date >= trend_start,
                LinkedInDailyMetric.report_date <= end,
            )
            .order_by(LinkedInDailyMetric.report_date)
        )
    ).all()

    trend = [
        {
            "date": r.report_date.isoformat(),
            "cv_added": r.cv_added,
            "messages_sent": r.messages_sent,
            "responses_received": r.responses_received,
        }
        for r in trend_rows
    ]

    return {
        "period": period,
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "me": me.dict() if me else None,
        "trend_14d": trend,
    }
