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
    PlacementAnalysis,
    PlacementByClient,
    PlacementByPerson,
    PowerCallingEntry,
    QuarterlyEntryRequirement,
    RekrutacjaDashboard,
    TeamPanel,
    TeamPanelCategory,
    TeamPanelSourcer,
    TeamPanelTacDl,
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
    # Prize amounts (PLN) — admin editable via /admin-config/scoring.
    "prize_1": 5000,
    "prize_2": 3000,
    "prize_3": 2000,
    # Business thresholds — admin editable via /admin-config/scoring.
    "power_calling_min_per_day": 3,
    "linkedin_cv_per_md_target": 5,
}

# Roster zespołu rekrutacji (Liga Mistrzów, Wyścig Miesięczny, Power Calling) jest
# wyznaczany przez kuratorowane tabele przypisań zarządzane w panelu admina:
#   dr_sourcer_category_assignments  (Sourcer ↔ Kategoria kompetencji)
#   dr_tac_delivery_lead_assignments (TAC ↔ Delivery Lead)
# NIE przez `users.role`. Po migracji DR→Nexus role w `users` są zanieczyszczone
# (AAD sync nadał `sourcer`/`recruiter` dziesiątkom userów ATS) i zdryfowane
# (Marlena/Diana awansowane na `delivery_lead`; Malwina/Sandra/Martyna W./Dawid
# trzymają KPI na koncie legacy z rolą `user`). Roster wskazuje konta data-bearing,
# więc join do KPI jest poprawny, a duplikaty (ASCII twins bez KPI) są pomijane.

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
                "prize_1": int(raw.get("prize_1", DEFAULT_SCORING["prize_1"])),
                "prize_2": int(raw.get("prize_2", DEFAULT_SCORING["prize_2"])),
                "prize_3": int(raw.get("prize_3", DEFAULT_SCORING["prize_3"])),
                "power_calling_min_per_day": int(
                    raw.get(
                        "power_calling_min_per_day",
                        DEFAULT_SCORING["power_calling_min_per_day"],
                    )
                ),
                "linkedin_cv_per_md_target": int(
                    raw.get(
                        "linkedin_cv_per_md_target",
                        DEFAULT_SCORING["linkedin_cv_per_md_target"],
                    )
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


def _compute_quarter_state(
    today: date, q_start: date, q_end: date
) -> tuple[int, int, bool]:
    """Liczy stan kwartału: dni do końca, progress %, is_completed.

    Returns (days_remaining, progress_pct, is_completed).
    """
    if today > q_end:
        return 0, 100, True
    if today < q_start:
        return (q_end - q_start).days, 0, False
    days_total = (q_end - q_start).days + 1
    days_passed = (today - q_start).days + 1
    days_remaining = max(0, (q_end - today).days)
    progress = min(100, int((days_passed / days_total) * 100))
    return days_remaining, progress, False


def _compute_month_state(today: date, m_start: date, m_end: date) -> tuple[int, bool]:
    """Liczy stan miesiąca: dni do końca + is_completed.

    Returns (days_remaining, is_completed).
    """
    if today > m_end:
        return 0, True
    if today < m_start:
        return (m_end - m_start).days, False
    return max(0, (m_end - today).days), False


def _is_last_month_of_quarter(month_date: date) -> bool:
    """Czy podany miesiąc to ostatni miesiąc swojego kwartału.

    Q1: Mar, Q2: Cze, Q3: Wrz, Q4: Gru.
    """
    return month_date.month in (3, 6, 9, 12)


def _compute_quarter_bounds(today: date) -> tuple[date, date, str]:
    """Liczy bounds bieżącego kwartału kalendarzowego dla Liga Mistrzów.

    Q1 = Sty-Mar, Q2 = Kwi-Cze, Q3 = Lip-Wrz, Q4 = Paź-Gru.

    Returns (start_date, end_date, label) — label format: "Q2 2026".

    DR aggregates Liga Mistrzów punkty po kwartale (Apr-Jun for Q2 2026),
    niezależnie od filtru `period` (week/month/year) wybranego przez usera.
    """
    quarter = (today.month - 1) // 3 + 1
    start_month = (quarter - 1) * 3 + 1
    start = date(today.year, start_month, 1)
    end_month = start_month + 2
    if end_month == 12:
        end = date(today.year, 12, 31)
    else:
        # Last day of end_month = first day of (end_month + 1) - 1 day
        next_after_end = date(today.year, end_month + 1, 1)
        end = next_after_end - timedelta(days=1)
    return start, end, f"Q{quarter} {today.year}"


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
    # Roster Ligi Mistrzów = kuratorowana lista zespołu rekrutacji zarządzana
    # w panelu admina (Sourcer↔Kategoria + TAC↔Delivery Lead), NIE filtr po
    # `users.role`. Powód: po migracji DR→Nexus role w `users` są zanieczyszczone
    # (AAD sync nadał `sourcer`/`recruiter` dziesiątkom userów ATS) oraz część
    # zawodników ma KPI na koncie legacy z rolą `user`/`delivery_lead`
    # (Malwina/Sandra/Martyna W./Dawid, Marlena DL). Roster wskazuje konta
    # data-bearing → join do KPI działa poprawnie i dedupe jest automatyczny.
    sql = text(
        """
        WITH roster AS (
            SELECT user_id AS uid FROM dr_sourcer_category_assignments
            UNION
            SELECT tac_user_id FROM dr_tac_delivery_lead_assignments
        )
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
        JOIN roster r ON r.uid = u.id
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.report_date BETWEEN :start_date AND :end_date
            AND k.is_draft = false
        WHERE u.is_active = true
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

        # Wszyscy członkowie pochodzą z rostera zespołu rekrutacji, więc cele
        # liczymy bezwarunkowo (rola w `users` bywa zdryfowana: user/delivery_lead).
        target_verif = work_days * 4
        target_recom = work_days * 4
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
          AND k.is_draft = false
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

    # ── Liga Mistrzów (kwartalna agregacja) ────────────────────────────────
    # DR pokazuje Q-level podium (3 miesiące zagregowane), niezależnie od
    # filtru `period` (week/month/year) — używamy bieżącego kwartału kalendarz.
    # Roster (sourcer-category ∪ tac-dl) obejmuje też awansowanych na DL
    # (Marlena/Diana), bo wskazuje konta data-bearing, nie filtruje po roli.
    # NOTE: `date` jako nazwa parametru query shadow'uje `from datetime import date`,
    # więc `date.today()` tu by zwracał AttributeError na stringu. Używamy `datetime.now().date()`.
    today = datetime.now().date()
    q_start, q_end, quarter_label = _compute_quarter_bounds(today)
    q_rows = (
        await db.execute(
            sql,  # ten sam SQL co główny query (roster-based) — z innymi bounds
            {
                "start_date": q_start,
                "end_date": q_end,
            },
        )
    ).all()
    quarterly_members: list[TeamMember] = []
    for row in q_rows:
        full_name = row.name or ""
        parts = full_name.split(" ", 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""
        # Quarterly targets — 3 miesiące * 20 dni roboczych. Wszyscy członkowie
        # pochodzą z rostera zespołu rekrutacji → cele bezwarunkowo.
        q_target_verif = 60 * 4
        q_target_recom = 60 * 4
        q_target_inter = max(1, int(row.recommendations * 0.1))
        q_target_place = 3  # Warunek udziału: minimum 3 placements/kwartał (1/msc)
        q_quality = (
            int((row.interviews / row.recommendations) * 100)
            if row.recommendations > 0
            else 0
        )
        q_metrics = UserMetrics(
            verifications=_calc_metric(row.verifications, q_target_verif),
            recommendations=_calc_metric(row.recommendations, q_target_recom),
            interviews=_calc_metric(row.interviews, q_target_inter),
            placements=_calc_metric(row.placements, q_target_place),
            quality_score=UserMetricValue(
                value=q_quality, target=10, percentage=q_quality
            ),
        )
        q_points = _calc_league_points(
            row.placements,
            row.interviews,
            row.recommendations,
            row.verifications,
            scoring,
        )
        quarterly_members.append(
            TeamMember(
                id=row.id,
                first_name=first_name,
                last_name=last_name,
                role=row.role,
                is_active=row.is_active,
                metrics=q_metrics,
                league_points=q_points,
                # DR parity: is_qualified ustawiamy poniżej (po _compute_quarter_state).
                is_qualified=True,
            )
        )

    # Liga Mistrzów state — countdown + progress + completion (DR parity).
    quarter_days_remaining, quarter_progress, quarter_is_completed = (
        _compute_quarter_state(today, q_start, q_end)
    )
    # Warunek udziału — minimum placement do dziś (1 placement/mc, więc:
    # miesiąc 1 = 1 placement, miesiąc 2 = 2 placement, miesiąc 3 = 3 placement).
    if quarter_is_completed:
        month_in_quarter = 3
    else:
        month_in_quarter = ((today.month - 1) % 3) + 1
    required_placements = month_in_quarter
    entry_requirement = QuarterlyEntryRequirement(
        min_placements=required_placements,
        total_required=3,
        month_in_quarter=month_in_quarter,
        description=(
            f"Wymagane minimum 1 placement miesięcznie (łącznie 3 w kwartale). "
            f"Do dziś: ≥ {required_placements} placement(ów)."
        ),
    )
    # Stempluj is_qualified na podstawie placement count vs required.
    for m in quarterly_members:
        m.is_qualified = m.metrics.placements.value >= required_placements

    league_ranking_quarterly = sorted(
        [m for m in quarterly_members if m.is_active],
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
        league_ranking_quarterly=league_ranking_quarterly,
        quarter_label=quarter_label,
        quarter_start=q_start,
        quarter_end=q_end,
        quarter_days_remaining=quarter_days_remaining,
        quarter_progress=quarter_progress,
        quarter_is_completed=quarter_is_completed,
        quarter_entry_requirement=entry_requirement,
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
        WHERE k.is_draft = false
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
            w.id,
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
            id=r.id,
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
        WHERE k.is_draft = false
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

    # Defense-in-depth — co-located whitelist assertion. The route-level
    # `pattern=` validator on `competition_type` query param protects this,
    # ale jeśli endpoint kiedyś będzie wywołany bez routing (np. testy, refactor),
    # ten assert blokuje SQL injection przez metric_col.
    _ALLOWED_METRICS = {"recommendations", "placements"}
    metric_col = (
        "recommendations" if competition_type == "recommendations" else "placements"
    )
    if metric_col not in _ALLOWED_METRICS:  # pragma: no cover — guard, unreachable
        raise ValueError(
            f"metric_col '{metric_col}' not in whitelist {_ALLOWED_METRICS}"
        )
    requirement = (
        "Min. 4 weryfikacji/dzień roboczy"
        if competition_type == "recommendations"
        else "Min. 2 placementy do kwalifikacji"
    )

    # Liga Mistrzów scoring (placement/interview/recommendation/verification points)
    # — używamy do liczenia kwartalnego lidera dla excluded_user_id w ostatnim
    # miesiącu kwartału.
    scoring = await _load_scoring(db)

    # DR shape: pełen wiersz z verifications + days_worked + per-day calc.
    # Filter HAVING usunięty — DR pokazuje WSZYSTKICH (włącznie z zerami), bo
    # quality info (verifications/dzień, precision rate) ma sens nawet
    # gdy main metric = 0.
    sql = text(
        f"""
        WITH roster AS (
            SELECT user_id AS uid FROM dr_sourcer_category_assignments
            UNION
            SELECT tac_user_id FROM dr_tac_delivery_lead_assignments
        )
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            COALESCE(SUM(k.{metric_col}), 0)::int AS metric_value,
            COALESCE(SUM(k.verifications), 0)::int AS verifications,
            COALESCE(SUM(k.recommendations), 0)::int AS recommendations,
            COALESCE(SUM(k.days_worked), 0)::int AS days_worked
        FROM users u
        JOIN roster r ON r.uid = u.id
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.report_date BETWEEN :start_date AND :end_date
            AND k.is_draft = false
        WHERE u.is_active = true
        GROUP BY u.id, u.name, u.role
        ORDER BY metric_value DESC, verifications DESC
        """  # noqa: S608 — metric_col z whitelist guard wyżej
    )
    rows = (
        await db.execute(
            sql,
            {
                "start_date": month_date,
                "end_date": month_end,
            },
        )
    ).all()

    # DR business rules (mirror server/src/routes/competitions.ts):
    VERIFICATION_REQUIREMENT = 4  # weryfikacji/dzień roboczy
    PRECISION_RATE_REQUIREMENT_PCT = 75  # od 2026-04
    PRECISION_RATE_ACTIVE_FROM = "2026-04"
    period_str = f"{month_date.year}-{month_date.month:02d}"
    is_precision_rate_active = (
        period_str >= PRECISION_RATE_ACTIVE_FROM
        and competition_type == "recommendations"
    )
    is_last_month_of_q = _is_last_month_of_quarter(month_date)
    min_qualification = 2 if competition_type == "placements" else None

    # Wyłączamy zwycięzcę kwartalnego z nagrody miesięcznej (tylko ostatni miesiąc Q).
    excluded_user_id: int | None = None
    if is_last_month_of_q:
        q_start, q_end, _ = _compute_quarter_bounds(month_date)
        q_leader_sql = text(
            """
            WITH roster AS (
                SELECT user_id AS uid FROM dr_sourcer_category_assignments
                UNION
                SELECT tac_user_id FROM dr_tac_delivery_lead_assignments
            )
            SELECT
                u.id,
                COALESCE(SUM(k.placements), 0) * :pts_p
                  + COALESCE(SUM(k.interviews), 0) * :pts_i
                  + COALESCE(SUM(k.recommendations), 0) * :pts_r
                  + COALESCE(SUM(k.verifications), 0) * :pts_v AS points
            FROM users u
            JOIN roster r ON r.uid = u.id
            LEFT JOIN dr_kpi_body_leasing k
                ON k.user_id = u.id
                AND k.report_date BETWEEN :qs AND :qe
                AND k.is_draft = false
            WHERE u.is_active = true
            GROUP BY u.id
            ORDER BY points DESC
            LIMIT 1
            """
        )
        q_leader_row = (
            await db.execute(
                q_leader_sql,
                {
                    "qs": q_start,
                    "qe": q_end,
                    "pts_p": scoring["placement"],
                    "pts_i": scoring["interview"],
                    "pts_r": scoring["recommendation"],
                    "pts_v": scoring["verification"],
                },
            )
        ).first()
        if q_leader_row:
            excluded_user_id = q_leader_row.id

    entries: list[MonthlyRaceEntry] = []
    for r in rows:
        days = r.days_worked or 0
        verif = r.verifications or 0
        recom = r.recommendations or 0
        verif_per_day = round(verif / days, 2) if days > 0 else 0.0
        precision_pct = int(round((recom / verif) * 100)) if verif > 0 else 0
        meets_verification = verif_per_day >= VERIFICATION_REQUIREMENT
        meets_precision = (
            not is_precision_rate_active
        ) or precision_pct >= PRECISION_RATE_REQUIREMENT_PCT
        if competition_type == "placements":
            is_qualified = r.metric_value >= (min_qualification or 0)
        else:
            is_qualified = meets_verification and meets_precision
        entries.append(
            MonthlyRaceEntry(
                user_id=r.id,
                user_name=r.name or "",
                role=r.role,
                metric_value=r.metric_value,
                per_day=(round(r.metric_value / days, 2) if days > 0 else 0.0),
                verifications=verif,
                days_worked=days,
                verifications_per_day=verif_per_day,
                precision_rate=precision_pct,
                meets_verification_requirement=meets_verification,
                meets_precision_requirement=meets_precision,
                is_qualified=is_qualified,
                is_excluded=(r.id == excluded_user_id),
            )
        )

    # Sortowanie po metric_value DESC (jak DR).
    entries.sort(key=lambda e: e.metric_value, reverse=True)
    # Re-rank po sort (no rank field but order matters for client #1/#2/#3 podium).

    # Current leader = pierwszy eligible (nie wykluczony + qualifies).
    current_leader_id: int | None = None
    for e in entries:
        if not e.is_excluded and e.is_qualified:
            current_leader_id = e.user_id
            break

    days_remaining, is_completed = _compute_month_state(
        date.today(), month_date, month_end
    )

    return MonthlyRace(
        competition_type=competition_type,
        month=period_str,
        voucher="Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
        requirement=requirement,
        entries=entries,
        period=period_str,
        month_name=POLISH_MONTH_NAMES[month_date.month - 1],
        year=month_date.year,
        days_remaining=days_remaining,
        is_completed=is_completed,
        min_qualification=min_qualification,
        verification_requirement=(
            VERIFICATION_REQUIREMENT if competition_type == "recommendations" else None
        ),
        precision_rate_requirement=(
            PRECISION_RATE_REQUIREMENT_PCT if is_precision_rate_active else None
        ),
        is_precision_rate_active=is_precision_rate_active,
        tie_breaker="Wyższa sumaryczna marża",
        is_last_month_of_quarter=is_last_month_of_q,
        excluded_user_id=excluded_user_id,
        current_leader_id=current_leader_id,
        prize="Voucher 1 500 PLN (Modivo, Douglas, Media Markt)",
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
        WITH roster AS (
            SELECT user_id AS uid FROM dr_sourcer_category_assignments
            UNION
            SELECT tac_user_id FROM dr_tac_delivery_lead_assignments
        )
        SELECT
            u.id,
            u.name,
            u.role::text AS role,
            COALESCE(SUM(k.verifications), 0)::int AS verifications,
            COALESCE(SUM(k.days_worked), 0)::int AS days_worked
        FROM users u
        JOIN roster r ON r.uid = u.id
        LEFT JOIN dr_kpi_body_leasing k
            ON k.user_id = u.id
            AND k.week_number = :wk
            AND EXTRACT(YEAR FROM k.report_date)::int = :yr
            AND k.is_draft = false
        WHERE u.is_active = true
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
            AND k.is_draft = false
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


@router.get(
    "/placement-analysis",
    response_model=PlacementAnalysis,
    summary="Analiza Placementów — breakdown wg osób + wg klientów",
)
async def get_placement_analysis(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    period: str = Query(default="month", pattern="^(week|month|year)$"),
    date_str: Optional[str] = Query(default=None, alias="date"),
    week_number: Optional[int] = Query(default=None),
    year: Optional[int] = Query(default=None),
) -> PlacementAnalysis:
    """Placementy z dr_placement_details zgrupowane per osoba + per klient.

    Port `PlacementRankingSection` z DR (titled "Analiza Placementów").
    """
    start, end, _ = _resolve_period_bounds(period, date_str, week_number, year)

    by_person_sql = text(
        """
        SELECT
            p.user_id,
            COALESCE(NULLIF(u.name, ''), u.email) AS user_name,
            u.role::text AS role,
            count(*)::int AS cnt
        FROM dr_placement_details p
        JOIN users u ON u.id = p.user_id
        WHERE p.placement_date BETWEEN :start_date AND :end_date
        GROUP BY p.user_id, u.name, u.email, u.role
        ORDER BY cnt DESC, user_name
        """
    )
    by_client_sql = text(
        """
        SELECT
            p.client_id,
            COALESCE(c.name, '—') AS client_name,
            count(*)::int AS cnt
        FROM dr_placement_details p
        LEFT JOIN dr_clients c ON c.id = p.client_id
        WHERE p.placement_date BETWEEN :start_date AND :end_date
        GROUP BY p.client_id, c.name
        ORDER BY cnt DESC, client_name
        """
    )
    params = {"start_date": start, "end_date": end}
    person_rows = (await db.execute(by_person_sql, params)).all()
    client_rows = (await db.execute(by_client_sql, params)).all()

    by_person = [
        PlacementByPerson(
            user_id=r.user_id,
            user_name=r.user_name or "",
            role=r.role,
            count=r.cnt,
        )
        for r in person_rows
    ]
    by_client = [
        PlacementByClient(
            client_id=r.client_id or 0,
            client_name=r.client_name or "—",
            count=r.cnt,
        )
        for r in client_rows
    ]
    total = sum(p.count for p in by_person)
    return PlacementAnalysis(by_person=by_person, by_client=by_client, total=total)


@router.get(
    "/team-panel",
    response_model=TeamPanel,
    summary="Zespół Rekrutacji - Przypisania (sourcer categories + TAC-DL)",
)
async def get_team_panel(
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
) -> TeamPanel:
    """Read-only display: Sourcerzy wg Kategorii + TAC-DL assignments.

    Port `RecruitmentTeamPanel` z DR — viewer-accessible (każdy zalogowany),
    w przeciwieństwie do admin RTM (CRUD, wymaga admina).
    """
    # Sourcer ↔ category z priority
    sc_sql = text(
        """
        SELECT
            c.id AS category_id,
            c.name AS category_name,
            COALESCE(c.sort_order, 0) AS sort_order,
            a.user_id,
            COALESCE(NULLIF(u.name, ''), u.email) AS sourcer_name,
            a.priority
        FROM dr_sourcer_category_assignments a
        JOIN dr_competence_categories c ON c.id = a.category_id
        JOIN users u ON u.id = a.user_id
        WHERE u.is_active = true
        ORDER BY c.sort_order, c.name, a.priority, sourcer_name
        """
    )
    sc_rows = (await db.execute(sc_sql)).all()
    cat_map: dict[int, TeamPanelCategory] = {}
    cat_order: list[int] = []
    for r in sc_rows:
        if r.category_id not in cat_map:
            cat_map[r.category_id] = TeamPanelCategory(
                category_id=r.category_id,
                category_name=r.category_name or "—",
                first_priority=[],
                second_priority=[],
            )
            cat_order.append(r.category_id)
        entry = TeamPanelSourcer(
            user_id=r.user_id, name=r.sourcer_name or "", priority=r.priority
        )
        if r.priority == 1:
            cat_map[r.category_id].first_priority.append(entry)
        else:
            cat_map[r.category_id].second_priority.append(entry)

    # TAC ↔ DL
    tac_sql = text(
        """
        SELECT
            a.delivery_lead_user_id AS dl_id,
            COALESCE(NULLIF(d.name, ''), d.email) AS dl_name,
            COALESCE(NULLIF(t.name, ''), t.email) AS tac_name
        FROM dr_tac_delivery_lead_assignments a
        JOIN users d ON d.id = a.delivery_lead_user_id
        JOIN users t ON t.id = a.tac_user_id
        ORDER BY dl_name, tac_name
        """
    )
    tac_rows = (await db.execute(tac_sql)).all()
    dl_map: dict[int, TeamPanelTacDl] = {}
    dl_order: list[int] = []
    for r in tac_rows:
        if r.dl_id not in dl_map:
            dl_map[r.dl_id] = TeamPanelTacDl(
                dl_user_id=r.dl_id, dl_name=r.dl_name or "", tac_names=[]
            )
            dl_order.append(r.dl_id)
        dl_map[r.dl_id].tac_names.append(r.tac_name or "")

    return TeamPanel(
        sourcer_categories=[cat_map[cid] for cid in cat_order],
        tac_dl=[dl_map[did] for did in dl_order],
    )
