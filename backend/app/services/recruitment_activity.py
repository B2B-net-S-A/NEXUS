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
    RecruitmentActivityState,
    RecruitmentActivitySummaryResponse,
    RecruitmentActivityTeamTotalsResponse,
    RecruitmentActivityWindow,
)
from app.services.insights_person_scope import outside_scope_user_ids
from app.services.kpi_engine import WARSAW
from app.services.credited_snapshot import CREDITED_FROM_SNAPSHOT_CTE, credited_bind
from app.services.kpi_targets import resolve_kpi_target


_KPI_ROLES = frozenset({UserRole.recruiter})
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
    CREDITED_FROM_SNAPSHOT_CTE
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


# Filtr osób szczegółów: wybrana osoba (`IN :user_ids`), cały zespół (każdy
# z kredytem — ta sama pula co suma w przeglądzie) albo kamienie bez osoby
# z zasługą (wiersz „Bez osoby z zasługą” w Insights → Zespół, 17.10.2026).
_PERSON_FILTER = "credited.credit_user IN :user_ids"
_TEAM_FILTER = "credited.credit_user IS NOT NULL"
_UNATTRIBUTED_FILTER = "credited.credit_user IS NULL"

# Stan pary „teraz” — z najnowszego wiersza etapu pary (lista „Kto się liczy”,
# 17.10.2026). Odrzucenie przez klienta czytamy jak `known_people_signal`:
# `ended_by='client'`, a wiersz sprzed tej kolumny liczy się, gdy osoba była
# u klienta. Kolejność warunków to pierwszeństwo: zatrudnienie i zakończenie
# pary wygrywają z zamkniętą rekrutacją.
DETAIL_STATES: tuple[RecruitmentActivityState, ...] = (
    "before_client",
    "waiting",
    "at_client",
    "hired",
    "rejected_by_client",
    "ended",
    "job_closed",
)

_DESCRIBED_CTE = """
    ,
    period_rows AS (
        SELECT credited.candidate_id,
               credited.job_id,
               credited.credit_user,
               credited.reached_at
        FROM credited
        WHERE {person_filter}
          AND credited.stage = :stage
          AND credited.reached_at >= :period_start
          AND credited.reached_at < :period_end
    ),
    candidate_jobs AS (
        SELECT candidate_id, count(DISTINCT job_id) AS jobs
        FROM period_rows
        GROUP BY candidate_id
    ),
    described AS (
        SELECT period_rows.candidate_id,
               period_rows.job_id,
               period_rows.credit_user,
               period_rows.reached_at,
               candidate_jobs.jobs AS candidate_jobs,
               mover.moved_by AS mover_id,
               latest.stage AS latest_stage,
               latest.moved_at AS latest_at,
               latest.rejection_reason_id,
               CASE
                   WHEN latest.stage IN ('hired', 'onboarding') THEN 'hired'
                   WHEN latest.stage = 'rejected' AND (
                       latest.ended_by = 'client'
                       OR (
                           latest.ended_by IS NULL
                           AND EXISTS (
                               SELECT 1 FROM candidate_stages sent
                               WHERE sent.candidate_id = period_rows.candidate_id
                                 AND sent.job_id = period_rows.job_id
                                 AND sent.stage::text IN (
                                     'cv_sent', 'client_interview',
                                     'acceptance', 'negotiation'
                                 )
                           )
                       )
                   ) THEN 'rejected_by_client'
                   WHEN latest.stage IN ('rejected', 'withdrawn') THEN 'ended'
                   WHEN job.status::text = 'closed' THEN 'job_closed'
                   WHEN latest.stage IN (
                       'client_interview', 'acceptance', 'negotiation'
                   ) THEN 'at_client'
                   WHEN latest.stage = 'cv_sent' THEN 'waiting'
                   ELSE 'before_client'
               END AS state
        FROM period_rows
        JOIN candidate_jobs ON candidate_jobs.candidate_id = period_rows.candidate_id
        JOIN jobs job ON job.id = period_rows.job_id
        -- Kto kliknął etap: wiersz, z którego `credited` wziął chwilę osiągnięcia
        -- (przy „Zweryfikowany” po akceptacji to `approved_at`).
        LEFT JOIN LATERAL (
            SELECT cs.moved_by
            FROM candidate_stages cs
            WHERE cs.candidate_id = period_rows.candidate_id
              AND cs.job_id = period_rows.job_id
              AND cs.stage::text = :stage
              AND (
                  cs.moved_at = period_rows.reached_at
                  OR cs.approved_at = period_rows.reached_at
              )
            ORDER BY cs.id
            LIMIT 1
        ) mover ON TRUE
        LEFT JOIN LATERAL (
            SELECT cs.stage::text AS stage,
                   cs.moved_at,
                   cs.ended_by,
                   cs.rejection_reason_id
            FROM candidate_stages cs
            WHERE cs.candidate_id = period_rows.candidate_id
              AND cs.job_id = period_rows.job_id
            ORDER BY cs.moved_at DESC, cs.id DESC
            LIMIT 1
        ) latest ON TRUE
    )
"""


def _with_user_ids(statement, person_filter: str):
    if person_filter == _PERSON_FILTER:
        return statement.bindparams(bindparam("user_ids", expanding=True))
    return statement


def _detail_summary_sql(person_filter: str):
    state_counts = ",\n           ".join(
        f"count(*) FILTER (WHERE state = '{state}') AS state_{state}"
        for state in DETAIL_STATES
    )
    return _with_user_ids(
        text(
            CREDITED_FROM_SNAPSHOT_CTE
            + _DESCRIBED_CTE.format(person_filter=person_filter)
            + f"""
    SELECT count(*) AS total,
           count(DISTINCT candidate_id) AS people,
           count(*) FILTER (
               WHERE mover_id IS NOT NULL AND mover_id = credit_user
           ) AS moved_by_credited,
           {state_counts},
           -- Dni z DynaReportera (1.01–11.10.2026): wiersz bez pary, więc
           -- nie ma go w `described`; licznik celów i tak go liczy.
           (
               SELECT count(*) FROM period_rows WHERE candidate_id IS NULL
           ) AS history_total
    FROM described
    """
        ),
        person_filter,
    )


def _detail_sql(person_filter: str):
    return _with_user_ids(
        text(
            CREDITED_FROM_SNAPSHOT_CTE
            + _DESCRIBED_CTE.format(person_filter=person_filter)
            + """
    SELECT described.candidate_id,
           trim(concat_ws(' ', candidate.name, candidate.lastname)) AS candidate_name,
           described.job_id,
           job.title AS job_title,
           job.working_title AS job_working_title,
           job.client_reference AS job_client_reference,
           coalesce(
               nullif(client.display_name, ''),
               nullif(client.name, ''),
               'Klient #' || client.id::text
           ) AS client_name,
           described.credit_user,
           credit.name AS credit_user_name,
           credit.role::text AS credit_user_role,
           described.reached_at,
           described.mover_id,
           mover.name AS mover_name,
           mover.role::text AS mover_role,
           described.state,
           described.latest_stage,
           described.latest_at,
           reason.name AS reason_name,
           described.candidate_jobs
    FROM described
    JOIN candidates candidate ON candidate.id = described.candidate_id
    JOIN jobs job ON job.id = described.job_id
    JOIN clients client ON client.id = job.client_id
    LEFT JOIN users credit ON credit.id = described.credit_user
    LEFT JOIN users mover ON mover.id = described.mover_id
    LEFT JOIN rejection_reasons reason ON reason.id = described.rejection_reason_id
    WHERE CAST(:state AS text) IS NULL OR described.state = CAST(:state AS text)
    ORDER BY described.reached_at DESC,
             described.candidate_id,
             described.job_id
    OFFSET :offset
    LIMIT :limit
    """
        ),
        person_filter,
    )


_DETAIL_SUMMARY_SQL = {
    "person": _detail_summary_sql(_PERSON_FILTER),
    "team": _detail_summary_sql(_TEAM_FILTER),
    "unattributed": _detail_summary_sql(_UNATTRIBUTED_FILTER),
}
_DETAIL_SQL = {
    "person": _detail_sql(_PERSON_FILTER),
    "team": _detail_sql(_TEAM_FILTER),
    "unattributed": _detail_sql(_UNATTRIBUTED_FILTER),
}
# Najdłuższy okres listy — jak okres „custom” w Insights (`MAX_CUSTOM_PERIOD_DAYS`).
_MAX_RANGE_DAYS = 366


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
    year = absolute // 12
    if year > 9999:
        raise ValueError(
            f"_shift_month result exceeds max representable year 9999 "
            f"(value={value}, delta={delta})"
        )
    return date(year, absolute % 12 + 1, 1)


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
    any_subject: bool = False,
) -> _ActivityAudience:
    """Kogo dotyczy widok.

    ``any_subject`` (lista „Kto się liczy”): wybrana osoba nie musi być aktywnym
    rekruterem. Tabela Insights → Zespół ma wiersze osób nieaktywnych i spoza
    ról KPI z kredytem w okresie, a ich liczba ma się dać otworzyć jako lista.
    Kto może patrzeć na kogo, nie zmienia się: inna osoba tylko dla ról z
    ``_TEAM_DETAIL_ROLES``.
    """
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
        if selected is None and any_subject:
            selected = (
                current_user
                if subject_user_id == current_user.id
                else await db.get(User, subject_user_id)
            )
            if selected is None:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Taka osoba nie istnieje.",
                )
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
        result = (
            (await db.execute(_OVERVIEW_SQL, {**params, **await credited_bind(db)}))
            .mappings()
            .all()
        )
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
    date_from: date | None = None,
    date_to: date | None = None,
    unattributed: bool = False,
    state: RecruitmentActivityState | None = None,
) -> RecruitmentActivityDetailResponse:
    """Wiersze za jedną liczbą — lista „Kto się liczy” i rozwinięcie kafla.

    Wiersze bierze z ``VERIFIER_ANCHORED_CTE`` jak licznik celów w górnym pasku
    (`kpi_engine.count_canonical_metric`), więc ``period_total`` dla osoby
    i okresu celu jest tą samą liczbą co w pasku.
    """
    if metric == "placement" and window == "day":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Placementy są raportowane wyłącznie miesięcznie.",
        )
    start_date, end_date = _detail_window(
        window,
        selected_day=selected_day,
        selected_month=selected_month,
        date_from=date_from,
        date_to=date_to,
    )

    if unattributed:
        if team_scope or subject_user_id is not None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Wybierz osobę, zespół albo kamienie bez osoby z zasługą.",
            )
        if not current_user.has_any_role(*_TEAM_DETAIL_ROLES):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Brak dostępu do imiennych szczegółów całego zespołu.",
            )
        scope = "unattributed"
        subject = None
    else:
        audience = await _activity_audience(
            db,
            current_user,
            subject_user_id,
            team_scope=team_scope,
            any_subject=True,
        )
        subject = audience.selected
        # Bez osoby i bez `scope=team` konto spoza ról KPI (np. „Automatyzacje”,
        # 0446) spadało do listy całego zespołu, choć jawne `scope=team` dawało
        # mu 403 (przegląd bezpieczeństwa 17.10.2026).
        if subject is None and not audience.can_view_team_details:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Brak dostępu do imiennych szczegółów całego zespołu.",
            )
        # Cały zespół = ta sama pula co suma kafla (R7-N9-1).
        scope = "person" if subject is not None else "team"

    period_start, period_end = _warsaw_bounds(start_date, end_date)
    params: dict = {
        "stage": _METRIC_STAGE[metric],
        "period_start": period_start,
        "period_end": period_end,
    }
    if subject is not None:
        params["user_ids"] = [subject.id]
    # `period_rows` czyta z `credited` tylko ten etap i ten okres.
    params.update(
        await credited_bind(
            db, stage=params["stage"], since=period_start, until=period_end
        )
    )

    summary = (await db.execute(_DETAIL_SUMMARY_SQL[scope], params)).mappings().one()
    listed_total = int(summary["total"] or 0)
    # Licznik celów liczy też tygodniowe wpisy DynaReportera sprzed 12.10.2026,
    # których nie da się rozpisać na osoby kandydatów — suma okresu je zawiera,
    # lista (i jej stronicowanie) nie.
    history_total = int(summary["history_total"] or 0)
    period_total = listed_total + history_total
    states = {
        name: int(summary[f"state_{name}"] or 0)
        for name in DETAIL_STATES
        if int(summary[f"state_{name}"] or 0) > 0
    }
    total = states.get(state, 0) if state is not None else listed_total
    rows = []
    if total:
        rows = (
            (
                await db.execute(
                    _DETAIL_SQL[scope],
                    {
                        **params,
                        "state": state,
                        "offset": (page - 1) * page_size,
                        "limit": page_size,
                    },
                )
            )
            .mappings()
            .all()
        )

    items = [_detail_item(row) for row in rows]
    return RecruitmentActivityDetailResponse(
        generated_at=datetime.now(timezone.utc),
        metric=metric,
        window=window,
        page=page,
        page_size=page_size,
        total=total,
        items=items,
        period_start=start_date,
        period_end=end_date - timedelta(days=1),
        scope=scope,
        subject=_person(subject) if subject is not None else None,
        people=int(summary["people"] or 0),
        moved_by_credited=int(summary["moved_by_credited"] or 0),
        states=states,
        state_filter=state,
        period_total=period_total,
        history_total=history_total,
    )


async def team_period_totals(
    db: AsyncSession,
    current_user: User,
    *,
    metrics: tuple[RecruitmentActivityMetric, ...],
    date_from: date,
    date_to: date,
) -> RecruitmentActivityTeamTotalsResponse:
    """Liczby zespołu za dni od–do dla kilku etapów w jednym żądaniu.

    Kafel „Wyniki zespołu” pytał listę „Kto się liczy” cztery razy (po jednym
    etapie), a każde pytanie to były dwa pełne `VERIFIER_ANCHORED_CTE`
    (27.10.2026). Liczba etapu to TEN SAM licznik co ``period_total`` listy
    zespołu — to samo zapytanie podsumowania, na jednej migawce `credited`.
    """
    await _activity_audience(db, current_user, None, team_scope=True, any_subject=True)
    start_date, end_date = _detail_window(
        "range",
        selected_day=date_from,
        selected_month=date_from.replace(day=1),
        date_from=date_from,
        date_to=date_to,
    )
    period_start, period_end = _warsaw_bounds(start_date, end_date)
    totals: dict[RecruitmentActivityMetric, int] = {}
    history: dict[RecruitmentActivityMetric, int] = {}
    for metric in metrics:
        stage = _METRIC_STAGE[metric]
        params: dict = {
            "stage": stage,
            "period_start": period_start,
            "period_end": period_end,
            **await credited_bind(
                db, stage=stage, since=period_start, until=period_end
            ),
        }
        summary = (
            (await db.execute(_DETAIL_SUMMARY_SQL["team"], params)).mappings().one()
        )
        history[metric] = int(summary["history_total"] or 0)
        totals[metric] = int(summary["total"] or 0) + history[metric]
    return RecruitmentActivityTeamTotalsResponse(
        generated_at=datetime.now(timezone.utc),
        period_start=start_date,
        period_end=end_date - timedelta(days=1),
        totals=totals,
        history=history,
    )


def _detail_window(
    window: RecruitmentActivityWindow,
    *,
    selected_day: date,
    selected_month: date,
    date_from: date | None,
    date_to: date | None,
) -> tuple[date, date]:
    """Dni listy jako półotwarte ``[start, end)`` w kalendarzu firmy."""
    if selected_day > date.max - timedelta(days=7):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Dzień jest poza zakresem kalendarza.",
        )
    if window == "day":
        return selected_day, selected_day + timedelta(days=1)
    if window == "week":
        # Tydzień celu „Rekomendacje w tygodniu”: od poniedziałku
        # (`kpi_engine.period_bounds`).
        monday = selected_day - timedelta(days=selected_day.weekday())
        return monday, monday + timedelta(days=7)
    if window == "range":
        if date_from is None or date_to is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Okres wymaga dat od i do.",
            )
        if date_from > date_to:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Data początku okresu jest późniejsza niż data końca.",
            )
        if (date_to - date_from).days + 1 > _MAX_RANGE_DAYS:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Okres może mieć najwyżej {_MAX_RANGE_DAYS} dni.",
            )
        if date_to >= date.max:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Data końca okresu jest poza zakresem.",
            )
        return date_from, date_to + timedelta(days=1)
    start = _month_start(selected_month)
    return start, _shift_month(start, 1)


def _detail_person(
    user_id: object, name: object, role: object
) -> RecruitmentActivityPerson | None:
    if user_id is None or name is None:
        return None
    return RecruitmentActivityPerson(
        id=int(user_id), name=str(name), role=str(role or "user")
    )


def _detail_item(row) -> RecruitmentActivityDetailItem:
    candidate_id = int(row["candidate_id"])
    job_id = int(row["job_id"])
    return RecruitmentActivityDetailItem(
        candidate=RecruitmentActivityCandidate(
            id=candidate_id,
            name=str(row["candidate_name"] or f"Kandydat #{candidate_id}"),
            href=f"/candidates/{candidate_id}",
        ),
        job=RecruitmentActivityJob(
            id=job_id,
            title=str(row["job_title"]),
            working_title=row["job_working_title"] or None,
            client_reference=row["job_client_reference"] or None,
            client_name=str(row["client_name"]),
            # Otwiera rekrutację z panelem tej osoby (jak link z powiadomienia).
            href=f"/jobs/{job_id}?candidate={candidate_id}",
        ),
        credited_user=_detail_person(
            row["credit_user"], row["credit_user_name"], row["credit_user_role"]
        ),
        reached_at=row["reached_at"],
        moved_by=_detail_person(row["mover_id"], row["mover_name"], row["mover_role"]),
        state=row["state"],
        state_stage=row["latest_stage"],
        state_since=row["latest_at"],
        state_reason=row["reason_name"] or None,
        candidate_jobs=max(int(row["candidate_jobs"] or 1), 1),
    )


__all__ = [
    "build_recruitment_activity_summary",
    "list_recruitment_activity_details",
]
