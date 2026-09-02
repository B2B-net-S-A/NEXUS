"""Canonical KPI activity read model used by the unified role dashboard.

The service deliberately reuses ``VERIFIER_ANCHORED_CTE``.  Counts and the
candidate drill-down therefore describe the very same first milestones as the
existing personal and team KPI panels instead of inventing a second funnel.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import bindparam, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.schemas.recruitment_activity import (
    RecruitmentActivityCandidate,
    RecruitmentActivityComparison,
    RecruitmentActivityDetailItem,
    RecruitmentActivityDetailResponse,
    RecruitmentActivityJob,
    RecruitmentActivityMetric,
    RecruitmentActivityMetricCounts,
    RecruitmentActivityPerson,
    RecruitmentActivityProgress,
    RecruitmentActivitySummaryResponse,
    RecruitmentActivityWindow,
)
from app.services.kpi_engine import WARSAW
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE, _resolve_target


_KPI_ROLES = frozenset({UserRole.sourcer, UserRole.tac, UserRole.recruiter})
_TEAM_DETAIL_ROLES = frozenset(
    {
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.finance,
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
    }
)
_METRIC_STAGE: dict[RecruitmentActivityMetric, str] = {
    "verification": "verified",
    "recommendation": "cv_sent",
    "interview": "interview",
    "acceptance": "acceptance",
    "placement": "hired",
}
_STAGE_METRIC = {stage: metric for metric, stage in _METRIC_STAGE.items()}
_BENCHMARK_MONTHS = 3


_OVERVIEW_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT credit_user, stage,
           count(*) FILTER (
               WHERE reached_at >= :day_start AND reached_at < :day_end
           ) AS day_count,
           count(*) FILTER (
               WHERE reached_at >= :month_start AND reached_at < :month_end
           ) AS month_count,
           count(*) FILTER (
               WHERE reached_at >= :benchmark_start
                 AND reached_at < :benchmark_end
           ) AS benchmark_count
    FROM credited
    WHERE credit_user IN :user_ids
      AND stage IN ('verified', 'cv_sent', 'interview', 'acceptance', 'hired')
      AND (
          (reached_at >= :day_start AND reached_at < :day_end)
          OR (reached_at >= :month_start AND reached_at < :month_end)
          OR (
              reached_at >= :benchmark_start
              AND reached_at < :benchmark_end
          )
      )
    GROUP BY credit_user, stage
    """
).bindparams(bindparam("user_ids", expanding=True))


_DETAIL_COUNT_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT count(*)
    FROM credited
    WHERE credit_user IN :user_ids
      AND stage = :stage
      AND reached_at >= :period_start
      AND reached_at < :period_end
    """
).bindparams(bindparam("user_ids", expanding=True))


_DETAIL_SQL = text(
    VERIFIER_ANCHORED_CTE
    + """
    SELECT credited.candidate_id,
           trim(concat_ws(' ', candidate.name, candidate.lastname)) AS candidate_name,
           credited.job_id,
           job.title AS job_title,
           coalesce(
               nullif(client.display_name, ''),
               nullif(client.name, ''),
               'Klient #' || client.id::text
           ) AS client_name,
           credited.credit_user,
           credit.name AS credit_user_name,
           credit.role::text AS credit_user_role,
           credited.reached_at
    FROM credited
    JOIN candidates candidate ON candidate.id = credited.candidate_id
    JOIN jobs job ON job.id = credited.job_id
    JOIN clients client ON client.id = job.client_id
    LEFT JOIN users credit ON credit.id = credited.credit_user
    WHERE credited.credit_user IN :user_ids
      AND credited.stage = :stage
      AND credited.reached_at >= :period_start
      AND credited.reached_at < :period_end
    ORDER BY credited.reached_at DESC,
             credited.candidate_id,
             credited.job_id
    OFFSET :offset
    LIMIT :limit
    """
).bindparams(bindparam("user_ids", expanding=True))


@dataclass(frozen=True)
class _ActivityAudience:
    users: tuple[User, ...]
    selected: User | None
    can_view_team_details: bool

    @property
    def user_ids(self) -> list[int]:
        if self.selected is not None:
            return [self.selected.id]
        return [user.id for user in self.users]


def _role_value(user: User) -> str:
    return user.role.value if user.role is not None else "user"


def _person(user: User) -> RecruitmentActivityPerson:
    return RecruitmentActivityPerson(
        id=user.id,
        name=user.name or f"Użytkownik #{user.id}",
        role=_role_value(user),
    )


def _month_start(value: date) -> date:
    return date(value.year, value.month, 1)


def _shift_month(value: date, delta: int) -> date:
    absolute = value.year * 12 + value.month - 1 + delta
    return date(absolute // 12, absolute % 12 + 1, 1)


def _warsaw_bounds(start: date, end: date) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, time.min, tzinfo=WARSAW),
        datetime.combine(end, time.min, tzinfo=WARSAW),
    )


def _benchmark_dates(selected_month: date, today: date) -> tuple[date, date]:
    """Three complete months, ending with a historical selected month.

    For the current or a future month we stop at the current month boundary so
    a partial month never depresses both averages.  For a historical month the
    selected month itself is complete and becomes the last bucket.
    """

    selected_start = _month_start(selected_month)
    current_start = _month_start(today)
    end_exclusive = (
        _shift_month(selected_start, 1)
        if selected_start < current_start
        else current_start
    )
    return _shift_month(end_exclusive, -_BENCHMARK_MONTHS), end_exclusive


async def _activity_audience(
    db: AsyncSession,
    current_user: User,
    subject_user_id: int | None,
    *,
    team_scope: bool = False,
) -> _ActivityAudience:
    if team_scope and subject_user_id is not None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Wybierz osobę albo cały zespół, nie oba zakresy naraz.",
        )
    active_users = (
        (
            await db.execute(
                select(User)
                .where(User.is_active.is_(True))
                .order_by(User.name, User.id)
            )
        )
        .scalars()
        .all()
    )
    users = tuple(user for user in active_users if user.has_any_role(*_KPI_ROLES))
    can_view_team_details = current_user.has_any_role(*_TEAM_DETAIL_ROLES)

    if subject_user_id is not None:
        if not can_view_team_details and subject_user_id != current_user.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Brak dostępu do szczegółów KPI innej osoby.",
            )
        selected = next((user for user in users if user.id == subject_user_id), None)
        if selected is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Aktywna osoba z KPI rekrutacyjnym nie istnieje.",
            )
        return _ActivityAudience(
            users=users,
            selected=selected,
            can_view_team_details=can_view_team_details,
        )

    if team_scope:
        if not can_view_team_details:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Brak dostępu do imiennych szczegółów całego zespołu.",
            )
        return _ActivityAudience(
            users=users,
            selected=None,
            can_view_team_details=can_view_team_details,
        )

    selected = current_user if current_user.has_any_role(*_KPI_ROLES) else None
    return _ActivityAudience(
        users=users,
        selected=selected,
        can_view_team_details=can_view_team_details,
    )


def _empty_metrics() -> dict[RecruitmentActivityMetric, dict[str, int]]:
    return {metric: {"day": 0, "month": 0} for metric in _METRIC_STAGE}


async def build_recruitment_activity_summary(
    db: AsyncSession,
    current_user: User,
    *,
    selected_day: date,
    selected_month: date,
    subject_user_id: int | None = None,
    team_scope: bool = False,
    today: date | None = None,
) -> RecruitmentActivitySummaryResponse:
    audience = await _activity_audience(
        db,
        current_user,
        subject_user_id,
        team_scope=team_scope,
    )
    month_start = _month_start(selected_month)
    month_end = _shift_month(month_start, 1)
    day_start_dt, day_end_dt = _warsaw_bounds(
        selected_day, selected_day + timedelta(days=1)
    )
    month_start_dt, month_end_dt = _warsaw_bounds(month_start, month_end)

    today_value = today or datetime.now(WARSAW).date()
    benchmark_start, benchmark_end = _benchmark_dates(
        selected_month,
        today_value,
    )
    benchmark_start_dt, benchmark_end_dt = _warsaw_bounds(
        benchmark_start, benchmark_end
    )
    counts = _empty_metrics()
    benchmark_by_user: dict[int, dict[str, int]] = {
        user.id: {"verified": 0, "hired": 0} for user in audience.users
    }
    selected_user_ids = set(audience.user_ids)
    if audience.users:
        rows = (
            (
                await db.execute(
                    _OVERVIEW_SQL,
                    {
                        "user_ids": [user.id for user in audience.users],
                        "day_start": day_start_dt,
                        "day_end": day_end_dt,
                        "month_start": month_start_dt,
                        "month_end": month_end_dt,
                        "benchmark_start": benchmark_start_dt,
                        "benchmark_end": benchmark_end_dt,
                    },
                )
            )
            .mappings()
            .all()
        )
        for row in rows:
            uid = int(row["credit_user"])
            stage = str(row["stage"])
            metric = _STAGE_METRIC.get(stage)
            if metric is None:
                continue
            if uid in selected_user_ids:
                counts[metric]["day"] += int(row["day_count"] or 0)
                counts[metric]["month"] += int(row["month_count"] or 0)
            if uid in benchmark_by_user and stage in {"verified", "hired"}:
                benchmark_by_user[uid][stage] = int(row["benchmark_count"] or 0)

    progress: RecruitmentActivityProgress | None = None
    if audience.selected is not None and selected_day == today_value:
        target = await _resolve_target(
            db,
            user=audience.selected,
            kpi_id="verifications_daily",
        )
        if target > 0:
            current = counts["verification"]["day"]
            progress = RecruitmentActivityProgress(
                current=current,
                target=target,
                progress_pct=round(100.0 * current / target, 1),
                remaining=max(target - current, 0),
            )

    people_count = len(audience.users)
    comparisons: list[RecruitmentActivityComparison] = []
    for metric, stage in (("verification", "verified"), ("placement", "hired")):
        team_total = sum(values[stage] for values in benchmark_by_user.values())
        team_average = (
            round(team_total / (people_count * _BENCHMARK_MONTHS), 1)
            if people_count
            else None
        )
        personal_average = None
        if audience.selected is not None:
            personal_average = round(
                benchmark_by_user.get(audience.selected.id, {}).get(stage, 0)
                / _BENCHMARK_MONTHS,
                1,
            )
        comparisons.append(
            RecruitmentActivityComparison(
                metric=metric,
                personal_average=personal_average,
                team_average=team_average,
                months=_BENCHMARK_MONTHS,
                period_start=benchmark_start,
                period_end=benchmark_end - timedelta(days=1),
                people=people_count,
            )
        )

    metric_models = [
        RecruitmentActivityMetricCounts(
            metric=metric,
            day=None if metric == "placement" else values["day"],
            month=values["month"],
        )
        for metric, values in counts.items()
    ]
    return RecruitmentActivitySummaryResponse(
        generated_at=datetime.now(timezone.utc),
        day=selected_day,
        month=month_start,
        scope="person" if audience.selected is not None else "team",
        can_view_team_details=audience.can_view_team_details,
        subject=_person(audience.selected) if audience.selected is not None else None,
        selectable_people=[
            _person(user)
            for user in audience.users
            if audience.can_view_team_details or user.id == current_user.id
        ],
        metrics=metric_models,
        verification_progress=progress,
        comparisons=comparisons,
    )


async def list_recruitment_activity_details(
    db: AsyncSession,
    current_user: User,
    *,
    metric: RecruitmentActivityMetric,
    window: RecruitmentActivityWindow,
    selected_day: date,
    selected_month: date,
    subject_user_id: int | None,
    team_scope: bool,
    page: int,
    page_size: int,
) -> RecruitmentActivityDetailResponse:
    if metric == "placement" and window == "day":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Placementy są raportowane wyłącznie miesięcznie.",
        )

    audience = await _activity_audience(
        db,
        current_user,
        subject_user_id,
        team_scope=team_scope,
    )
    if window == "day":
        start_date = selected_day
        end_date = selected_day + timedelta(days=1)
    else:
        start_date = _month_start(selected_month)
        end_date = _shift_month(start_date, 1)
    period_start, period_end = _warsaw_bounds(start_date, end_date)

    user_ids = audience.user_ids
    total = 0
    rows = []
    if user_ids:
        params = {
            "user_ids": user_ids,
            "stage": _METRIC_STAGE[metric],
            "period_start": period_start,
            "period_end": period_end,
        }
        total = int(await db.scalar(_DETAIL_COUNT_SQL, params) or 0)
        rows = (
            (
                await db.execute(
                    _DETAIL_SQL,
                    {
                        **params,
                        "offset": (page - 1) * page_size,
                        "limit": page_size,
                    },
                )
            )
            .mappings()
            .all()
        )

    items = [
        RecruitmentActivityDetailItem(
            candidate=RecruitmentActivityCandidate(
                id=int(row["candidate_id"]),
                name=str(row["candidate_name"] or f"Kandydat #{row['candidate_id']}"),
                href=f"/candidates/{row['candidate_id']}",
            ),
            job=RecruitmentActivityJob(
                id=int(row["job_id"]),
                title=str(row["job_title"]),
                client_name=str(row["client_name"]),
                href=f"/jobs/{row['job_id']}",
            ),
            credited_user=(
                RecruitmentActivityPerson(
                    id=int(row["credit_user"]),
                    name=str(row["credit_user_name"]),
                    role=str(row["credit_user_role"] or "user"),
                )
                if row["credit_user"] is not None
                and row["credit_user_name"] is not None
                else None
            ),
            reached_at=row["reached_at"],
        )
        for row in rows
    ]
    return RecruitmentActivityDetailResponse(
        generated_at=datetime.now(timezone.utc),
        metric=metric,
        window=window,
        page=page,
        page_size=page_size,
        total=total,
        items=items,
    )


__all__ = [
    "build_recruitment_activity_summary",
    "list_recruitment_activity_details",
]
