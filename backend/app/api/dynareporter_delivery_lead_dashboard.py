"""DynaReporter Delivery Lead dashboard endpoint.

Port `/delivery-lead` z artur-t-96/InfraReporter:
- summary: team-wide DL stats per user + team aggregates
- team-history: ostatnie 12 miesięcy team-wide trend
- trend/{user_id}: ostatnie N miesięcy hit-ratio per user

Filter `role = 'delivery_lead'` + aktywni LUB którzy mieli wpisy w okresie.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.analytics.capabilities import (
    AnalyticsCapability,
    require_dynareporter_section,
)
from app.core.database import get_db
from app.schemas.dr_delivery_lead_dashboard import (
    DLDashboard,
    DLMember,
    DLTeamHistoryRow,
    DLTeamStats,
    DLTrendRow,
)

router = APIRouter()

HIT_RATIO_TARGET = 30  # %


_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


def _require_legacy_team_dashboard_scope(current_user: User) -> None:
    """Keep the frozen organization-wide report out of Delivery Lead scope.

    The canonical Delivery Lead dashboard is relationship-aware.  This legacy
    table has no client–TAC dimension, so allowing a Delivery Lead here would
    silently fall back to organization-wide named metrics.
    """

    if not current_user.has_any_role(
        UserRole.admin,
        UserRole.head_of_recruitment,
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Legacy organization-wide Delivery Lead report is restricted; "
                "use /api/dashboard/v2/delivery-lead"
            ),
        )


@router.get(
    "/dashboard",
    response_model=DLDashboard,
    summary="Pełen Delivery Lead dashboard (team summary + team history)",
)
async def get_dashboard(
    current_user: User = Depends(
        require_dynareporter_section("delivery-lead", AnalyticsCapability.VIEW_TEAM_KPI)
    ),
    db: AsyncSession = Depends(get_db),
    start_date: Optional[str] = Query(
        default=None,
        pattern=_DATE_RE,
        description="YYYY-MM-DD start filter on report_month",
    ),
    end_date: Optional[str] = Query(
        default=None,
        pattern=_DATE_RE,
        description="YYYY-MM-DD end filter on report_month",
    ),
) -> DLDashboard:
    """Zwraca pełen DL dashboard. Bez parametrów = all-time aggregate.

    Filter `(:start IS NULL OR k.report_month >= :start)` pattern używany w
    obu instancjach `k` i podzapytaniu `k2`. Zamiast budować fragment SQL i
    interpolować przez f-string (poprzednia wersja z `replace('k.', 'k2.')`
    była fragile — quality check HIGH #2), używamy zawsze tych samych
    parametrów `:start_date` i `:end_date` z pełnym NULL-check wzorcem.

    `CAST(:date AS date)` analogicznie do fixu w yearly-stats (PR #252) —
    asyncpg potrzebuje explicit cast dla parametru używanego w `IS NULL`.

    Same param appears bare elsewhere (`k.report_month >= :start_date`); asyncpg
    infers DATE from that usage and fails to encode the Python `str` (Sentry
    NEXUS-BE-V — 88 events). Parse to `datetime.date` once so every binding
    sees the correct type. NULL handling stays at the CAST(:x AS date) IS NULL
    sites (Python `None` → SQL NULL works for both date and text columns).
    """
    _require_legacy_team_dashboard_scope(current_user)
    start_date_obj = (
        datetime.strptime(start_date, "%Y-%m-%d").date() if start_date else None
    )
    end_date_obj = datetime.strptime(end_date, "%Y-%m-%d").date() if end_date else None
    params = {"start_date": start_date_obj, "end_date": end_date_obj}

    # Per-DL aggregates — single text() z bound params, brak f-string SQL.
    sql_per_dl = text(
        """
        SELECT
            u.id,
            u.name,
            u.is_active,
            COALESCE(SUM(k.requests), 0)::int AS total_requests,
            COALESCE(SUM(k.placements), 0)::int AS total_placements,
            COALESCE(SUM(k.vacancies), 0)::int AS total_vacancies,
            COALESCE(SUM(k.open_requests), 0)::int AS total_open_requests,
            COALESCE(SUM(k.open_vacancies), 0)::int AS total_open_vacancies,
            CASE
                WHEN COALESCE(SUM(k.requests), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.placements), 0)::DECIMAL /
                     COALESCE(SUM(k.requests), 0)) * 100, 1
                )
                ELSE 0
            END AS hit_ratio,
            CASE
                WHEN COALESCE(SUM(k.vacancies), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.placements), 0)::DECIMAL /
                     COALESCE(SUM(k.vacancies), 0)) * 100, 1
                )
                ELSE 0
            END AS fill_rate,
            CASE
                WHEN COALESCE(SUM(k.requests), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.vacancies), 0)::DECIMAL /
                     COALESCE(SUM(k.requests), 0)), 1
                )
                ELSE 0
            END AS avg_vacancies_per_request
        FROM users u
        LEFT JOIN dr_kpi_delivery_lead k ON u.id = k.user_id
            AND (CAST(:start_date AS date) IS NULL OR k.report_month >= :start_date)
            AND (CAST(:end_date AS date) IS NULL OR k.report_month <= :end_date)
        WHERE u.role::text = 'delivery_lead'
          AND (
              u.is_active = true
              OR EXISTS (
                  SELECT 1 FROM dr_kpi_delivery_lead k2
                  WHERE k2.user_id = u.id
                    AND (CAST(:start_date AS date) IS NULL OR k2.report_month >= :start_date)
                    AND (CAST(:end_date AS date) IS NULL OR k2.report_month <= :end_date)
              )
          )
        GROUP BY u.id, u.name, u.is_active
        ORDER BY hit_ratio DESC, total_placements DESC
        """
    )
    rows = (await db.execute(sql_per_dl, params)).all()
    delivery_leads: list[DLMember] = []
    for i, row in enumerate(rows):
        hit_ratio = float(row.hit_ratio or 0)
        delivery_leads.append(
            DLMember(
                id=row.id,
                name=row.name or "",
                is_active=row.is_active,
                requests=row.total_requests,
                placements=row.total_placements,
                vacancies=row.total_vacancies,
                open_requests=row.total_open_requests,
                open_vacancies=row.total_open_vacancies,
                hit_ratio=hit_ratio,
                fill_rate=float(row.fill_rate or 0),
                avg_vacancies_per_request=float(row.avg_vacancies_per_request or 0),
                hit_ratio_target=HIT_RATIO_TARGET,
                target_achieved=hit_ratio >= HIT_RATIO_TARGET,
                rank=i + 1,
            )
        )

    # Team totals (all DL data, including inactive past employees)
    sql_team = text(
        """
        SELECT
            COALESCE(SUM(k.requests), 0)::int AS total_requests,
            COALESCE(SUM(k.placements), 0)::int AS total_placements,
            COALESCE(SUM(k.vacancies), 0)::int AS total_vacancies,
            COALESCE(SUM(k.open_requests), 0)::int AS total_open_requests,
            COALESCE(SUM(k.open_vacancies), 0)::int AS total_open_vacancies
        FROM dr_kpi_delivery_lead k
        WHERE (CAST(:start_date AS date) IS NULL OR k.report_month >= :start_date)
          AND (CAST(:end_date AS date) IS NULL OR k.report_month <= :end_date)
        """
    )
    team_row = (await db.execute(sql_team, params)).first()
    # DR parity: liczymy average TYLKO z DLs które mają dane (requests > 0).
    # Powód: Nexus.users ma duplikaty po DR→Nexus migracji (legacy DR user
    # + Nexus user → same osoba, 2 rows w users). Te duplikaty mają 0 KPI bo
    # cała aktywność jest pod jednym user_id. Liczenie 17 DLs zamiast 8 daje
    # 13% zamiast realnych 30% Hit Ratio. DR Render ma `is_active && department`
    # filter który eliminuje duplikaty, my filtrujemy po realnej aktywności.
    active_dls_with_data = [
        dl for dl in delivery_leads if dl.is_active and dl.requests > 0
    ]
    team_stats = DLTeamStats(
        total_requests=team_row.total_requests if team_row else 0,
        total_placements=team_row.total_placements if team_row else 0,
        total_vacancies=team_row.total_vacancies if team_row else 0,
        total_open_requests=team_row.total_open_requests if team_row else 0,
        total_open_vacancies=team_row.total_open_vacancies if team_row else 0,
        average_hit_ratio=(
            round(
                sum(dl.hit_ratio for dl in active_dls_with_data)
                / len(active_dls_with_data),
                1,
            )
            if active_dls_with_data
            else 0.0
        ),
        average_fill_rate=(
            round(
                sum(dl.fill_rate for dl in active_dls_with_data)
                / len(active_dls_with_data),
                1,
            )
            if active_dls_with_data
            else 0.0
        ),
        achieving_target=sum(1 for dl in active_dls_with_data if dl.target_achieved),
        active_dls_count=len(active_dls_with_data),
    )

    # Team history (last 12 months)
    sql_history = """
        SELECT
            k.report_month::text AS month,
            COALESCE(SUM(k.requests), 0)::int AS requests,
            COALESCE(SUM(k.vacancies), 0)::int AS vacancies,
            COALESCE(SUM(k.placements), 0)::int AS placements,
            CASE
                WHEN COALESCE(SUM(k.requests), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.placements), 0)::DECIMAL /
                     COALESCE(SUM(k.requests), 0)) * 100, 1
                )
                ELSE 0
            END AS hit_ratio,
            CASE
                WHEN COALESCE(SUM(k.vacancies), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.placements), 0)::DECIMAL /
                     COALESCE(SUM(k.vacancies), 0)) * 100, 1
                )
                ELSE 0
            END AS fill_rate
        FROM dr_kpi_delivery_lead k
        GROUP BY k.report_month
        ORDER BY k.report_month DESC
        LIMIT 12
    """
    history_rows = (await db.execute(text(sql_history))).all()
    team_history = [
        DLTeamHistoryRow(
            month=h.month,
            requests=h.requests,
            vacancies=h.vacancies,
            placements=h.placements,
            hit_ratio=float(h.hit_ratio or 0),
            fill_rate=float(h.fill_rate or 0),
        )
        for h in reversed(history_rows)  # chronological asc dla wykresu
    ]

    # Period label
    if start_date or end_date:
        period_label = f"{start_date or '…'} → {end_date or '…'}"
    else:
        period_label = "All-time"

    return DLDashboard(
        delivery_leads=delivery_leads,
        team_stats=team_stats,
        team_history=team_history,
        hit_ratio_target=HIT_RATIO_TARGET,
        period_label=period_label,
        period_start=start_date_obj,
        period_end=end_date_obj,
    )


@router.get(
    "/trend/{user_id}",
    response_model=list[DLTrendRow],
    summary="Trend Hit Ratio dla konkretnego DL (ostatnie N miesięcy)",
)
async def get_trend(
    user_id: int,
    current_user: User = Depends(
        require_dynareporter_section("delivery-lead", AnalyticsCapability.VIEW_TEAM_KPI)
    ),
    db: AsyncSession = Depends(get_db),
    months: int = Query(default=6, ge=1, le=24),
) -> list[DLTrendRow]:
    """Zwraca trend Hit-Ratio per użytkownik za ostatnie `months` mies."""
    _require_legacy_team_dashboard_scope(current_user)
    sql = """
        SELECT
            k.report_month::text AS month,
            COALESCE(SUM(k.requests), 0)::int AS requests,
            COALESCE(SUM(k.placements), 0)::int AS placements,
            CASE
                WHEN COALESCE(SUM(k.requests), 0) > 0
                THEN ROUND(
                    (COALESCE(SUM(k.placements), 0)::DECIMAL /
                     COALESCE(SUM(k.requests), 0)) * 100, 1
                )
                ELSE 0
            END AS hit_ratio
        FROM dr_kpi_delivery_lead k
        WHERE k.user_id = :user_id
        GROUP BY k.report_month
        ORDER BY k.report_month DESC
        LIMIT :months
    """
    rows = (await db.execute(text(sql), {"user_id": user_id, "months": months})).all()
    return [
        DLTrendRow(
            month=r.month,
            requests=r.requests,
            placements=r.placements,
            hit_ratio=float(r.hit_ratio or 0),
        )
        for r in reversed(rows)
    ]


# 2026-07-20: usunięta trasa POST /entry (adminowy upsert miesięcznego KPI
# Delivery Leada do dr_kpi_delivery_lead). Ręczne wprowadzanie statystyk
# wygaszone — NEXUS liczy te liczby sam z kontraktów i etapów kandydatów,
# a wynik pokazuje /insights. GET-y poniżej/powyżej zostają: karmią widoki
# historyczne, które nadal czytają zamrożone dane.
