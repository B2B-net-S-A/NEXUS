"""DynaReporter Rekrutacja mega-dashboard endpoint.

Port `/rekrutacja` z oryginalnego DR (artur-t-96/InfraReporter,
`server/src/routes/kpi.ts` + `client/src/pages/Rekrutacja.tsx`).

Endpoints:
- GET /api/dynareporter/rekrutacja/dashboard  — pełen dashboard (KPI cards,
  funnel, performance table, league ranking)
- GET /api/dynareporter/rekrutacja/available-weeks — tygodnie z danymi

Uprawnienia:
- Każdy zalogowany user widzi widok (dashboard team-wide).
- Endpoint NIE filtruje po current_user (team view, nie personal).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.schemas.dr_rekrutacja import (
    AccelerationPath,
    AccelerationPathEntry,
    AvailableWeek,
    FunnelStage,
    HallOfFameEntry,
    LinkedInPerformanceRow,
    MonthlyRace,
    MonthlyRaceEntry,
    PowerCallingEntry,
    RekrutacjaDashboard,
    TeamMember,
    TeamSummary,
    UserMetrics,
    UserMetricValue,
    YearlyStatsRow,
)

logger = logging.getLogger("dynareporter.rekrutacja")

router = APIRouter()

# Liga Mistrzów scoring system — fallback gdy dr_system_config nieczytany.
DEFAULT_SCORING = {
    "placement": 150,
    "interview": 15,
    "recommendation": 5,
    "verification": 0,
}

# Role które liczą się w widoku zespołu rekrutacji.
RECRUITMENT_ROLES = ("sourcer", "tac", "recruiter")

POLISH_MONTH_NAMES = [
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
]


async def _load_scoring(db: AsyncSession) -> dict[str, int]:
    """Czyta system punktowy Ligi Mistrzów z dr_system_config."""
    try:
        row = (
            await db.execute(
                text(
                    "SELECT value FROM dr_system_config "
                    "WHERE key = 'champions_league_scoring' LIMIT 1"
                )
            )
        ).first()
        if row and row[0]:
            raw = row[0]
            return {
                "placement": int(raw.get("placement", DEFAULT_SCORING["placement"])),
                "interview": int(raw.get("interview", DEFAULT_SCORING["interview"])),
                "recommendation": int(
                    raw.get("recommendation", DEFAULT_SCORING["recommendation"])
                ),
                "verification": int(
                    raw.get("verification", DEFAULT_SCORING["verification"])
                ),
            }
    except Exception:
        # Jeśli klucza nie ma lub błąd parsowania — fallback do statycznego.
        # Loguj z exc_info żeby Sentry/operators widzieli problem (np.
        # connection failure, SSL reset, asyncpg pool exhaustion).
        logger.warning(
            "Failed to load champions_league_scoring; using DEFAULT_SCORING",
            exc_info=True,
        )
    return dict(DEFAULT_SCORING)


def _resolve_period_bounds(
    period: str,
    date_str: Optional[str],
    week_number: Optional[int],
    year: Optional[int],
) -> tuple[date, date, str]:
    """Liczy [start, end] (włącznie) + label dla okresu.

    - week: na podstawie ISO week + year
    - month: na podstawie YYYY-MM-DD (zostaje miesiąc z tej daty)
    - year: pierwszy/ostatni dzień roku z `date_str` lub bieżącego
    """
    today = date.today()
    if period == "week":
        wk = week_number or int(today.isocalendar().week)
        yr = year or today.year
        # ISO week → poniedziałek tygodnia
        jan4 = date(yr, 1, 4)
        week1_monday = jan4 - timedelta(days=jan4.isoweekday() - 1)
        start = week1_monday + timedelta(weeks=wk - 1)
        end = start + timedelta(days=6)
        return start, end, f"Tydzień {wk}/{yr}"
    if period == "month":
        if date_str:
            try:
                d = datetime.strptime(date_str, "%Y-%m-%d").date()
            except ValueError:
                d = today
        else:
            d = today
        start = d.replace(day=1)
        # Ostatni dzień miesiąca = pierwszy dzień następnego - 1 dzień
        if start.month == 12:
            next_month = start.replace(year=start.year + 1, month=1)
        else:
            next_month = start.replace(month=start.month + 1)
        end = next_month - timedelta(days=1)
        return start, end, f"{POLISH_MONTH_NAMES[start.month - 1]} {start.year}"
    # year (default fallback)
    if date_str:
        try:
            d = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            d = today
    else:
        d = today
    start = date(d.year, 1, 1)
    end = date(d.year, 12, 31)
    return start, end, f"Rok {start.year}"


def _calc_metric(value: int, target: int) -> UserMetricValue:
    """Buduje UserMetricValue z value + target."""
    percentage = round((value / target) * 100) if target > 0 else 0
    return UserMetricValue(value=value, target=target, percentage=percentage)


def _calc_league_points(
    placements: int,
    interviews: int,
    recommendations: int,
    verifications: int,
    scoring: dict[str, int],
) -> int:
    """Liga Mistrzów scoring: placement×150 + interview×15 + recommendation×5."""
    return (
        placements * scoring["placement"]
        + interviews * scoring["interview"]
        + recommendations * scoring["recommendation"]
        + verifications * scoring["verification"]
    )


def _build_funnel(
    verifications: int,
    recommendations: int,
    interviews: int,
    placements: int,
) -> list[FunnelStage]:
    """Buduje 4 etapy lejka konwersji."""

    def _pct(num: int, denom: int) -> float:
        return round((num / denom) * 100, 1) if denom > 0 else 0.0

    return [
        FunnelStage(
            label="Weryfikacje → Rekomendacje",
            short_label="Wer → Rek",
            percentage=_pct(recommendations, verifications),
            numerator=recommendations,
            denominator=verifications,
        ),
        FunnelStage(
            label="Rekomendacje → Interviews",
            short_label="Rek → Int",
            percentage=_pct(interviews, recommendations),
            numerator=interviews,
            denominator=recommendations,
        ),
        FunnelStage(
            label="Interviews → Placements",
            short_label="Int → Plac",
            percentage=_pct(placements, interviews),
            numerator=placements,
            denominator=interviews,
        ),
        FunnelStage(
            label="Overall (Wer → Plac)",
            short_label="Overall",
            percentage=_pct(placements, verifications),
            numerator=placements,
            denominator=verifications,
        ),
    ]


@router.get(
    "/dashboard",
    response_model=RekrutacjaDashboard,
    summary="Pełen dashboard Rekrutacji (team-wide aggregations)",
)
async def get_dashboard(
    current_user: CurrentUser,  # noqa: ARG001 — wymagamy zalogowanego, ale endpoint zwraca widok team
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="month", pattern="^(week|month|year)$"),
    date: Optional[str] = Query(  # noqa: A002 — backward compat z DR API
        default=None,
        description="YYYY-MM-DD dla period=month|year",
    ),
    weekNumber: Optional[int] = Query(default=None, ge=1, le=53),  # noqa: N803
    year: Optional[int] = Query(default=None, ge=2020, le=2100),
) -> RekrutacjaDashboard:
    """Zwraca pełen Rekrutacja dashboard z agregatami team-wide.

    Domyślnie: bieżący miesiąc (jeśli brak parametrów).
    """
    start, end, period_label = _resolve_period_bounds(period, date, weekNumber, year)
    scoring = await _load_scoring(db)

    # Per-user agregaty + COUNT(DISTINCT report_date) jako days_reported.
    # Filter: tylko rekruci-team roles + (aktywny LUB miał wpis w okresie).
    sql = text(
        """
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            u.is_active,
            COALESCE(SUM(k.verifications), 0)::int AS verifications,
            COALESCE(SUM(k.recommendations), 0)::int AS recommendations,
            COALESCE(SUM(k.interviews), 0)::int AS interviews,
            COALESCE(SUM(k.placements), 0)::int AS placements,
            COALESCE(SUM(k.requests), 0)::int AS requests,
            COUNT(DISTINCT k.report_date)::int AS days_reported
        FROM users u
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.report_date BETWEEN :start_date AND :end_date
            AND (k.is_draft = false OR k.is_draft IS NULL)
        WHERE u.role::text = ANY(:roles)
          AND (
              u.is_active = true
              OR EXISTS (
                  SELECT 1 FROM dr_kpi_body_leasing k2
                  WHERE k2.user_id = u.id
                    AND k2.report_date BETWEEN :start_date AND :end_date
                    AND (k2.is_draft = false OR k2.is_draft IS NULL)
              )
          )
        GROUP BY u.id, u.name, u.role, u.is_active
        ORDER BY u.name
        """
    )
    rows = (
        await db.execute(
            sql,
            {
                "start_date": start,
                "end_date": end,
                "roles": list(RECRUITMENT_ROLES),
            },
        )
    ).all()

    # Cele zależne od okresu (heurystyka jak w oryginale).
    if period == "week":
        work_days = 5
    elif period == "month":
        work_days = 20
    else:
        work_days = 250

    members: list[TeamMember] = []
    for row in rows:
        # `name` może być "Imię Nazwisko" — rozdzielamy na pierwszą i resztę.
        full_name = row.name or ""
        parts = full_name.split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        target_verif = work_days * 4 if row.role in RECRUITMENT_ROLES else 0
        target_recom = work_days * 4 if row.role in RECRUITMENT_ROLES else 0
        target_inter = max(1, int(row.recommendations * 0.1))
        target_place = 1
        quality_score = (
            int((row.interviews / row.recommendations) * 100)
            if row.recommendations > 0
            else 0
        )

        metrics = UserMetrics(
            verifications=_calc_metric(row.verifications, target_verif),
            recommendations=_calc_metric(row.recommendations, target_recom),
            interviews=_calc_metric(row.interviews, target_inter),
            placements=_calc_metric(row.placements, target_place),
            quality_score=UserMetricValue(
                value=quality_score, target=10, percentage=quality_score
            ),
        )
        league_points = _calc_league_points(
            row.placements,
            row.interviews,
            row.recommendations,
            row.verifications,
            scoring,
        )
        members.append(
            TeamMember(
                id=row.id,
                first_name=first_name,
                last_name=last_name,
                role=row.role,
                is_active=row.is_active,
                metrics=metrics,
                league_points=league_points,
            )
        )

    # Team summary z osobnego query (suma wszystkich, nie tylko widocznych).
    team_sql = text(
        """
        SELECT
            COALESCE(SUM(k.verifications), 0)::int AS total_verifications,
            COALESCE(SUM(k.recommendations), 0)::int AS total_recommendations,
            COALESCE(SUM(k.interviews), 0)::int AS total_interviews,
            COALESCE(SUM(k.placements), 0)::int AS total_placements
        FROM dr_kpi_body_leasing k
        WHERE k.report_date BETWEEN :start_date AND :end_date
          AND (k.is_draft = false OR k.is_draft IS NULL)
        """
    )
    team_row = (
        await db.execute(team_sql, {"start_date": start, "end_date": end})
    ).first()
    total_verif = team_row.total_verifications if team_row else 0
    total_recom = team_row.total_recommendations if team_row else 0
    total_inter = team_row.total_interviews if team_row else 0
    total_place = team_row.total_placements if team_row else 0

    active_members = [m for m in members if m.is_active]
    avg_quality = (
        sum(m.metrics.quality_score.value for m in active_members)
        // len(active_members)
        if active_members
        else 0
    )

    team_summary = TeamSummary(
        total_verifications=total_verif,
        total_recommendations=total_recom,
        total_interviews=total_inter,
        total_placements=total_place,
        average_quality_score=avg_quality,
    )

    funnel = _build_funnel(total_verif, total_recom, total_inter, total_place)

    # League ranking: aktywni rekruci-team, sortowani po points DESC.
    league_ranking = sorted(
        [m for m in members if m.is_active],
        key=lambda m: m.league_points,
        reverse=True,
    )

    return RekrutacjaDashboard(
        period=period,
        period_label=period_label,
        period_start=start,
        period_end=end,
        team_summary=team_summary,
        funnel=funnel,
        users=members,
        league_ranking=league_ranking,
        scoring=scoring,
    )


@router.get(
    "/available-weeks",
    response_model=list[AvailableWeek],
    summary="Lista tygodni z danymi KPI (do dropdown'a w UI)",
)
async def get_available_weeks(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=52, ge=1, le=200),
) -> list[AvailableWeek]:
    """Zwraca ostatnie N tygodni z wpisami KPI, sortowane DESC."""
    sql = text(
        """
        SELECT DISTINCT
            k.week_number,
            EXTRACT(YEAR FROM k.report_date)::int AS year
        FROM dr_kpi_body_leasing k
        WHERE (k.is_draft = false OR k.is_draft IS NULL)
        ORDER BY year DESC, week_number DESC
        LIMIT :lim
        """
    )
    rows = (await db.execute(sql, {"lim": limit})).all()
    return [
        AvailableWeek(
            week_number=row.week_number,
            year=row.year,
            label=f"Tydzień {row.week_number}/{row.year}",
            has_data=True,
        )
        for row in rows
    ]


# =============================================================================
# Follow-up subsections (Hall of Fame + Stats Roczne + LinkedIn + Wyścigi + PC)
# =============================================================================


@router.get(
    "/hall-of-fame",
    response_model=list[HallOfFameEntry],
    summary="Historic Hall of Fame z dr_competition_winners",
)
async def get_hall_of_fame(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    limit: int = Query(default=100, ge=1, le=500),
) -> list[HallOfFameEntry]:
    """Zwraca historyczne zwycięstwa (Q-quarterly + monthly Rec + Plac)."""
    sql = text(
        """
        SELECT
            w.competition_type,
            w.period,
            w.rank,
            w.user_id,
            u.name AS user_name,
            COALESCE(w.points, 0) AS points,
            COALESCE(w.metric_value, 0) AS metric_value,
            w.prize
        FROM dr_competition_winners w
        LEFT JOIN users u ON u.id = w.user_id
        ORDER BY w.period DESC, w.competition_type, w.rank
        LIMIT :lim
        """
    )
    rows = (await db.execute(sql, {"lim": limit})).all()
    return [
        HallOfFameEntry(
            competition_type=r.competition_type,
            period=r.period,
            rank=r.rank,
            user_id=r.user_id,
            user_name=r.user_name or "(deleted user)",
            points=r.points,
            metric_value=r.metric_value,
            prize=r.prize,
        )
        for r in rows
    ]


@router.get(
    "/yearly-stats",
    response_model=list[YearlyStatsRow],
    summary="Tygodniowe agregaty KPI dla wykresu Statystyki Roczne",
)
async def get_yearly_stats(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    year: int = Query(default=None, ge=2020, le=2100),
) -> list[YearlyStatsRow]:
    """Per-tydzień agregaty Wer/Rek/Int/Plac za wybrany rok (default: bieżący)."""
    sql = text(
        """
        SELECT
            k.week_number,
            EXTRACT(YEAR FROM k.report_date)::int AS year,
            COALESCE(SUM(k.verifications), 0)::int AS verifications,
            COALESCE(SUM(k.recommendations), 0)::int AS recommendations,
            COALESCE(SUM(k.interviews), 0)::int AS interviews,
            COALESCE(SUM(k.placements), 0)::int AS placements
        FROM dr_kpi_body_leasing k
        WHERE (k.is_draft = false OR k.is_draft IS NULL)
          AND (CAST(:year AS int) IS NULL OR EXTRACT(YEAR FROM k.report_date)::int = :year)
        GROUP BY k.week_number, EXTRACT(YEAR FROM k.report_date)
        ORDER BY year ASC, k.week_number ASC
        """
    )
    rows = (await db.execute(sql, {"year": year})).all()
    return [
        YearlyStatsRow(
            week_label=f"T{r.week_number} {r.year}",
            week_number=r.week_number,
            year=r.year,
            verifications=r.verifications,
            recommendations=r.recommendations,
            interviews=r.interviews,
            placements=r.placements,
        )
        for r in rows
    ]


@router.get(
    "/monthly-race",
    response_model=MonthlyRace,
    summary="Wyścig Rekomendacji / Placementów (miesięczne competitions)",
)
async def get_monthly_race(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    competition_type: str = Query(
        default="recommendations", pattern="^(recommendations|placements)$"
    ),
    month: str | None = Query(
        default=None, description="YYYY-MM (default: bieżący miesiąc)"
    ),
) -> MonthlyRace:
    """Zwraca leaders w miesiącu dla danego typu competition.

    Wymóg: min 4 weryfikacji/dzień roboczy (rekomendacje) lub min 2 placementy
    (placementy). Voucher 1500 PLN.
    """
    today = date.today()
    if month:
        try:
            month_date = datetime.strptime(f"{month}-01", "%Y-%m-%d").date()
        except ValueError:
            month_date = today.replace(day=1)
    else:
        month_date = today.replace(day=1)
    # End of month
    if month_date.month == 12:
        next_month = month_date.replace(year=month_date.year + 1, month=1)
    else:
        next_month = month_date.replace(month=month_date.month + 1)
    month_end = next_month - timedelta(days=1)

    metric_col = (
        "recommendations" if competition_type == "recommendations" else "placements"
    )
    requirement = (
        "Min. 4 weryfikacji/dzień roboczy"
        if competition_type == "recommendations"
        else "Min. 2 placementy do kwalifikacji"
    )

    sql = text(
        f"""
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            COALESCE(SUM(k.{metric_col}), 0)::int AS metric_value,
            COALESCE(SUM(k.days_worked), 0)::int AS days_worked
        FROM users u
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.report_date BETWEEN :start_date AND :end_date
            AND (k.is_draft = false OR k.is_draft IS NULL)
        WHERE u.role::text = ANY(:roles)
          AND u.is_active = true
        GROUP BY u.id, u.name, u.role
        HAVING COALESCE(SUM(k.{metric_col}), 0) > 0
        ORDER BY metric_value DESC
        """  # noqa: S608 — metric_col z whitelist
    )
    rows = (
        await db.execute(
            sql,
            {
                "start_date": month_date,
                "end_date": month_end,
                "roles": list(RECRUITMENT_ROLES),
            },
        )
    ).all()
    entries = [
        MonthlyRaceEntry(
            user_id=r.id,
            user_name=r.name or "",
            role=r.role,
            metric_value=r.metric_value,
            per_day=(
                round(r.metric_value / r.days_worked, 2) if r.days_worked > 0 else 0.0
            ),
        )
        for r in rows
    ]
    return MonthlyRace(
        competition_type=competition_type,
        month=f"{month_date.year}-{month_date.month:02d}",
        voucher="Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
        requirement=requirement,
        entries=entries,
    )


@router.get(
    "/power-calling",
    response_model=list[PowerCallingEntry],
    summary="Power Calling — efektywność weryfikacji/dzień roboczy",
)
async def get_power_calling(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    week_number: int | None = Query(default=None, ge=1, le=53),
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> list[PowerCallingEntry]:
    """Per-osoba: weryfikacje/dzień_roboczy w wybranym tygodniu.

    Default: poprzedni tydzień (porównanie z bieżącym może być niekompletne).
    """
    today = date.today()
    iso = today.isocalendar()
    target_week = week_number or iso.week
    target_year = year or iso.year

    sql = text(
        """
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            COALESCE(SUM(k.verifications), 0)::int AS verifications,
            COALESCE(SUM(k.days_worked), 0)::int AS days_worked
        FROM users u
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.week_number = :wk
            AND EXTRACT(YEAR FROM k.report_date)::int = :yr
            AND (k.is_draft = false OR k.is_draft IS NULL)
        WHERE u.role::text = ANY(:roles)
          AND u.is_active = true
        GROUP BY u.id, u.name, u.role
        ORDER BY (CASE WHEN COALESCE(SUM(k.days_worked),0)>0
                       THEN COALESCE(SUM(k.verifications),0)::float
                            / COALESCE(SUM(k.days_worked),0)
                       ELSE 0 END) ASC
        """
    )
    rows = (
        await db.execute(
            sql,
            {
                "wk": target_week,
                "yr": target_year,
                "roles": list(RECRUITMENT_ROLES),
            },
        )
    ).all()
    return [
        PowerCallingEntry(
            user_id=r.id,
            user_name=r.name or "",
            role=r.role,
            verifications=r.verifications,
            days_worked=r.days_worked,
            per_day=(
                round(r.verifications / r.days_worked, 2) if r.days_worked > 0 else 0.0
            ),
            week_label=f"Tydzień {target_week}/{target_year}",
        )
        for r in rows
    ]


@router.get(
    "/linkedin-performance",
    response_model=list[LinkedInPerformanceRow],
    summary="LinkedIn Performance — per-TAC CV added / messages / response rate",
)
async def get_linkedin_performance(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="month", pattern="^(week|month|year)$"),
    date_str: str | None = Query(default=None, alias="date"),
    week_number: int | None = Query(default=None, alias="weekNumber", ge=1, le=53),
    year: int | None = Query(default=None, ge=2020, le=2100),
) -> list[LinkedInPerformanceRow]:
    """Per-TAC LinkedIn farming stats (CV added, msg sent, response rate)."""
    start, end, _ = _resolve_period_bounds(period, date_str, week_number, year)

    sql = text(
        """
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            COALESCE(SUM(k.linkedin_cv_added), 0)::int AS cv_added,
            COALESCE(SUM(k.linkedin_messages_sent), 0)::int AS messages_sent,
            COALESCE(SUM(k.linkedin_responses_received), 0)::int AS responses_received,
            COALESCE(SUM(k.days_worked), 0)::int AS days_worked
        FROM users u
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.report_date BETWEEN :start_date AND :end_date
            AND (k.is_draft = false OR k.is_draft IS NULL)
        WHERE u.role::text = 'tac'
          AND u.is_active = true
        GROUP BY u.id, u.name, u.role
        ORDER BY cv_added DESC, messages_sent DESC
        """
    )
    rows = (await db.execute(sql, {"start_date": start, "end_date": end})).all()
    return [
        LinkedInPerformanceRow(
            user_id=r.id,
            user_name=r.name or "",
            role=r.role,
            cv_added=r.cv_added,
            messages_sent=r.messages_sent,
            responses_received=r.responses_received,
            response_rate=(
                round((r.responses_received / r.messages_sent) * 100, 1)
                if r.messages_sent > 0
                else 0.0
            ),
            cv_per_md=(
                round(r.cv_added / r.days_worked, 2) if r.days_worked > 0 else 0.0
            ),
        )
        for r in rows
    ]


# =============================================================================
# Acceleration Path (Junior→Senior, Senior→Expert progression)
# =============================================================================


def _calc_acceleration_status(
    placements_6m: int,
    placements_12m: int,
    threshold_6m: int,
    threshold_12m: int,
    months_elapsed: int,
    start_date: date,
) -> tuple[str, str | None]:
    """Liczy status + next_promotion_date dla Acceleration Path.

    - Awans gdy placements_6m >= threshold_6m LUB placements_12m >= threshold_12m.
    - "Na ścieżce" gdy progress >= 2/3 wymagań.
    - "Poniżej tempa" gdy progress < 2/3 wymagań i months_elapsed >= 3.
    """
    achieved = (placements_6m >= threshold_6m) or (placements_12m >= threshold_12m)
    if achieved:
        # Awans od pierwszego dnia kolejnego miesiąca po osiągnięciu
        today = date.today()
        if today.month == 12:
            promote = today.replace(year=today.year + 1, month=1, day=1)
        else:
            promote = today.replace(month=today.month + 1, day=1)
        return (
            f"Awans od {promote.strftime('%d.%m.%Y')}",
            promote.strftime("%Y-%m-%d"),
        )

    progress_ratio = max(
        placements_6m / threshold_6m if threshold_6m > 0 else 0,
        placements_12m / threshold_12m if threshold_12m > 0 else 0,
    )
    if progress_ratio >= 0.67 or months_elapsed < 3:
        return ("Na ścieżce", None)
    return ("Poniżej tempa", None)


@router.get(
    "/acceleration-path",
    response_model=AccelerationPath,
    summary="Acceleration Path — Junior→Senior i Senior→Expert progression",
)
async def get_acceleration_path(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> AccelerationPath:
    """Zwraca 2 listy: Junior→Senior i Senior→Expert z postępem placements.

    Progresja liczona z `dr_placement_details` (placement_date),
    seniority data z `dr_user_seniority`.

    Progi:
    - Junior → Senior: 6 placement w 6mc LUB 12 placement w 12mc
    - Senior → Expert: 12 placement w 6mc LUB 24 placement w 12mc
    """
    today = date.today()
    six_m_ago = today - timedelta(days=180)
    twelve_m_ago = today - timedelta(days=365)

    # JUNIOR → SENIOR
    # Single LEFT JOIN + COUNT FILTER zamiast 2 correlated subqueries per row
    # (quality check HIGH #1). Wymaga composite idx (user_id, placement_date)
    # na dr_placement_details (migracja 0115).
    sql_junior = text(
        """
        SELECT
            s.user_id,
            u.name,
            u.role::text AS role,
            s.acceleration_start_date AS start_date,
            COUNT(*) FILTER (WHERE p.placement_date >= :six_m)::int AS placements_6m,
            COUNT(*) FILTER (WHERE p.placement_date >= :twelve_m)::int AS placements_12m
        FROM dr_user_seniority s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN dr_placement_details p ON p.user_id = s.user_id
        WHERE s.seniority_level = 'junior'
          AND s.acceleration_start_date IS NOT NULL
          AND u.is_active = true
        GROUP BY s.user_id, u.name, u.role, s.acceleration_start_date
        ORDER BY placements_6m DESC, u.name
        """
    )
    junior_rows = (
        await db.execute(sql_junior, {"six_m": six_m_ago, "twelve_m": twelve_m_ago})
    ).all()
    junior_to_senior: list[AccelerationPathEntry] = []
    ready_count = 0
    for r in junior_rows:
        months_elapsed = (
            ((today.year - r.start_date.year) * 12) + (today.month - r.start_date.month)
            if r.start_date
            else 0
        )
        status, promote_date = _calc_acceleration_status(
            r.placements_6m,
            r.placements_12m,
            threshold_6m=6,
            threshold_12m=12,
            months_elapsed=months_elapsed,
            start_date=r.start_date,
        )
        if promote_date:
            ready_count += 1
        junior_to_senior.append(
            AccelerationPathEntry(
                user_id=r.user_id,
                user_name=r.name,
                role=r.role,
                start_date=r.start_date.strftime("%Y-%m-%d") if r.start_date else "",
                months_elapsed=max(0, months_elapsed),
                placements_6m=r.placements_6m,
                placements_12m=r.placements_12m,
                threshold_6m=6,
                threshold_12m=12,
                status=status,
                next_promotion_date=promote_date,
            )
        )

    # SENIOR → EXPERT (analogiczna refaktoryzacja co JUNIOR → SENIOR)
    sql_senior = text(
        """
        SELECT
            s.user_id,
            u.name,
            u.role::text AS role,
            s.senior_since AS start_date,
            COUNT(*) FILTER (WHERE p.placement_date >= :six_m)::int AS placements_6m,
            COUNT(*) FILTER (WHERE p.placement_date >= :twelve_m)::int AS placements_12m
        FROM dr_user_seniority s
        JOIN users u ON u.id = s.user_id
        LEFT JOIN dr_placement_details p ON p.user_id = s.user_id
        WHERE s.seniority_level = 'senior'
          AND s.senior_since IS NOT NULL
          AND u.is_active = true
        GROUP BY s.user_id, u.name, u.role, s.senior_since
        ORDER BY placements_6m DESC, u.name
        """
    )
    senior_rows = (
        await db.execute(sql_senior, {"six_m": six_m_ago, "twelve_m": twelve_m_ago})
    ).all()
    senior_to_expert: list[AccelerationPathEntry] = []
    for r in senior_rows:
        months_elapsed = (
            ((today.year - r.start_date.year) * 12) + (today.month - r.start_date.month)
            if r.start_date
            else 0
        )
        status, promote_date = _calc_acceleration_status(
            r.placements_6m,
            r.placements_12m,
            threshold_6m=12,
            threshold_12m=24,
            months_elapsed=months_elapsed,
            start_date=r.start_date,
        )
        if promote_date:
            ready_count += 1
        senior_to_expert.append(
            AccelerationPathEntry(
                user_id=r.user_id,
                user_name=r.name,
                role=r.role,
                start_date=r.start_date.strftime("%Y-%m-%d") if r.start_date else "",
                months_elapsed=max(0, months_elapsed),
                placements_6m=r.placements_6m,
                placements_12m=r.placements_12m,
                threshold_6m=12,
                threshold_12m=24,
                status=status,
                next_promotion_date=promote_date,
            )
        )

    # Counts
    counts_sql = text(
        """
        SELECT seniority_level, count(*)::int AS cnt
        FROM dr_user_seniority s
        JOIN users u ON u.id = s.user_id
        WHERE u.is_active = true
        GROUP BY seniority_level
        """
    )
    cnt_rows = (await db.execute(counts_sql)).all()
    counts_map = {r.seniority_level: r.cnt for r in cnt_rows}

    return AccelerationPath(
        junior_to_senior=junior_to_senior,
        senior_to_expert=senior_to_expert,
        junior_count=counts_map.get("junior", 0),
        senior_count=counts_map.get("senior", 0),
        expert_count=counts_map.get("expert", 0),
        ready_for_promotion=ready_count,
    )
