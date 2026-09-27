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

from app.core.cache import cache_get, cache_set, cache_single_flight
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
from app.services.insights_person_scope import outside_scope_user_ids
from app.services.kpi_engine import WARSAW
from app.services.kpi_panel import VERIFIER_ANCHORED_CTE
from app.services.kpi_targets import resolve_kpi_target


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
# Runda 7 (R7-N9-2, decyzja właściciela 26.09.2026): „Interview" = WYŁĄCZNIE
# rozmowy u klienta (`client_interview`) — ta sama kolumna co „Rozmowa
# u klienta" na Tablicy. Kod `interview` to w szablonie domyślnym etap QC CV
# („Przepuszczony przez DZ"), czyli praca PRZED wysłaniem CV.
_METRIC_STAGE: dict[RecruitmentActivityMetric, str] = {
    "verification": "verified",
    "recommendation": "cv_sent",
    "interview": "client_interview",
    "acceptance": "acceptance",
    "placement": "hired",
}
_STAGE_METRIC = {stage: metric for metric, stage in _METRIC_STAGE.items()}
_BENCHMARK_MONTHS = 3
_OVERVIEW_CACHE_TTL_SECONDS = 120


# Runda 7 (R7-N9-1, R7-N9-3): przegląd liczy KAŻDEGO z kredytem w oknie, nie
# tylko aktywne konta ról KPI — lustro `kpi_team.compute_team_panel` (zmiana
# 2026-08-13: dezaktywacja nie może wstecznie kasować wyniku zespołu). Bez
# filtra osób wynik jest wspólny dla wszystkich oglądających, więc trzymamy go
# w cache (jeden wykonawca) i zawężamy do osoby w Pythonie.
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
    WHERE credit_user IS NOT NULL
      AND stage IN (
          'verified', 'cv_sent', 'client_interview', 'acceptance', 'hired'
      )
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
)


# Filtr osób szczegółów: wybrana osoba (`IN :user_ids`) albo cały zespół
# (każdy z kredytem — ta sama pula co suma w przeglądzie).
_PERSON_FILTER = "credited.credit_user IN :user_ids"
_TEAM_FILTER = "credited.credit_user IS NOT NULL"


def _detail_count_sql(person_filter: str):
    statement = text(
        VERIFIER_ANCHORED_CTE
        + f"""
    SELECT count(*)
    FROM credited
    WHERE {person_filter}
      AND credited.stage = :stage
      AND credited.reached_at >= :period_start
      AND credited.reached_at < :period_end
    """
    )
    if person_filter == _PERSON_FILTER:
        statement = statement.bindparams(bindparam("user_ids", expanding=True))
    return statement


def _detail_sql(person_filter: str):
    statement = text(
        VERIFIER_ANCHORED_CTE
        + f"""
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
    WHERE {person_filter}
      AND credited.stage = :stage
      AND credited.reached_at >= :period_start
      AND credited.reached_at < :period_end
    ORDER BY credited.reached_at DESC,
             credited.candidate_id,
             credited.job_id
    OFFSET :offset
    LIMIT :limit
    """
    )
    if person_filter == _PERSON_FILTER:
        statement = statement.bindparams(bindparam("user_ids", expanding=True))
    return statement


_DETAIL_COUNT_PERSON_SQL = _detail_count_sql(_PERSON_FILTER)
_DETAIL_COUNT_TEAM_SQL = _detail_count_sql(_TEAM_FILTER)
_DETAIL_PERSON_SQL = _detail_sql(_PERSON_FILTER)
_DETAIL_TEAM_SQL = _detail_sql(_TEAM_FILTER)


@dataclass(frozen=True)
class _ActivityAudience:
    users: tuple[User, ...]
    selected: User | None
    can_view_team_details: bool


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


async def _overview_rows(
    db: AsyncSession, *, cache_key: str, params: dict
) -> list[dict]:
    """Liczniki (osoba × etap) dla okna dnia, miesiąca i porównania.

    Wynik nie zależy od oglądającego, więc jest wspólny: jedno przeliczenie
    `VERIFIER_ANCHORED_CTE` na 120 s zamiast jednego na każde wejście
    i każde odpytanie kafla co 5 min (R7-N9-3).
    """

    key = f"dashboard:recruitment_activity:overview:v2:{cache_key}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    async with cache_single_flight(key, db=db):
        cached = await cache_get(key)
        if cached is not None:
            return cached
        result = (await db.execute(_OVERVIEW_SQL, params)).mappings().all()
        rows = [
            {
                "credit_user": int(row["credit_user"]),
                "stage": str(row["stage"]),
                "day_count": int(row["day_count"] or 0),
                "month_count": int(row["month_count"] or 0),
                "benchmark_count": int(row["benchmark_count"] or 0),
            }
            for row in result
        ]
        await cache_set(
            key, rows, ttl_seconds=_OVERVIEW_CACHE_TTL_SECONDS, jitter_seconds=15
        )
        return rows


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
    # Porównanie „średnia zespołu": aktywne osoby z rolą KPI (też z zerem) plus
    # KAŻDY, kto ma kredyt w oknie porównania — jak tabela `kpi_team`.
    benchmark_by_user: dict[int, dict[str, int]] = {
        user.id: {"verified": 0, "hired": 0} for user in audience.users
    }
    rows = await _overview_rows(
        db,
        cache_key=(
            f"{selected_day.isoformat()}:{month_start.isoformat()}:"
            f"{benchmark_start.isoformat()}:{benchmark_end.isoformat()}"
        ),
        params={
            "day_start": day_start_dt,
            "day_end": day_end_dt,
            "month_start": month_start_dt,
            "month_end": month_end_dt,
            "benchmark_start": benchmark_start_dt,
            "benchmark_end": benchmark_end_dt,
        },
    )
    selected_id = audience.selected.id if audience.selected is not None else None
    for row in rows:
        uid = int(row["credit_user"])
        stage = str(row["stage"])
        metric = _STAGE_METRIC.get(stage)
        if metric is None:
            continue
        if selected_id is None or uid == selected_id:
            counts[metric]["day"] += int(row["day_count"] or 0)
            counts[metric]["month"] += int(row["month_count"] or 0)
        benchmark = int(row["benchmark_count"] or 0)
        if stage in {"verified", "hired"} and benchmark > 0:
            person = benchmark_by_user.setdefault(uid, {"verified": 0, "hired": 0})
            person[stage] = benchmark

    progress: RecruitmentActivityProgress | None = None
    if audience.selected is not None and selected_day == today_value:
        target = await resolve_kpi_target(
            db,
            user=audience.selected,
            kpi_id="daily_first_verifications",
        )
        if target > 0:
            current = counts["verification"]["day"]
            progress = RecruitmentActivityProgress(
                current=current,
                target=target,
                progress_pct=round(100.0 * current / target, 1),
                remaining=max(target - current, 0),
            )

    # Runda 8 (R8-V2-3): konta administracyjne (bez roli rekrutacyjnej, jak
    # w tabelach osób Insights — `insights_person_scope`) są poza średnią
    # zespołu. Legacy `classified_fallback` daje im kredyt za masowe
    # domykanie pipeline'u, co zawyżało średnią placementów. Sumy zespołu
    # (liczniki miesiąca) zostają bez zmian. Osoby z listy KPI mają rolę
    # z zakresu, więc sprawdzamy tylko pozostałych z kredytem.
    audience_ids = {user.id for user in audience.users}
    outside_ids = await outside_scope_user_ids(
        db, (uid for uid in benchmark_by_user if uid not in audience_ids)
    )
    team_pool = {
        uid: values
        for uid, values in benchmark_by_user.items()
        if uid not in outside_ids
    }
    people_count = len(team_pool)
    comparisons: list[RecruitmentActivityComparison] = []
    for metric, stage in (("verification", "verified"), ("placement", "hired")):
        team_total = sum(values[stage] for values in team_pool.values())
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

    params: dict = {
        "stage": _METRIC_STAGE[metric],
        "period_start": period_start,
        "period_end": period_end,
    }
    if audience.selected is not None:
        params["user_ids"] = [audience.selected.id]
        count_sql, detail_sql = _DETAIL_COUNT_PERSON_SQL, _DETAIL_PERSON_SQL
    else:
        # Cały zespół = ta sama pula co suma kafla (R7-N9-1).
        count_sql, detail_sql = _DETAIL_COUNT_TEAM_SQL, _DETAIL_TEAM_SQL
    total = int(await db.scalar(count_sql, params) or 0)
    rows = []
    if total:
        rows = (
            (
                await db.execute(
                    detail_sql,
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
