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

from datetime import date, datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.schemas.dr_rekrutacja import (
    AvailableWeek,
    FunnelStage,
    RekrutacjaDashboard,
    TeamMember,
    TeamSummary,
    UserMetrics,
    UserMetricValue,
)

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
        pass
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
