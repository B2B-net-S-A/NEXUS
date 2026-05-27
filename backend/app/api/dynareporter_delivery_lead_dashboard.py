"""DynaReporter Delivery Lead dashboard endpoint.

Port `/delivery-lead` z artur-t-96/InfraReporter:
- summary: team-wide DL stats per user + team aggregates
- team-history: ostatnie 12 miesięcy team-wide trend
- trend/{user_id}: ostatnie N miesięcy hit-ratio per user

Filter `role = 'delivery_lead'` + aktywni LUB którzy mieli wpisy w okresie.
"""

from __future__ import annotations

import logging

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.schemas.dr_delivery_lead_dashboard import (
    DLDashboard,
    DLMember,
    DLTeamHistoryRow,
    DLTeamStats,
    DLTrendRow,
    DLUpsert,
)

logger = logging.getLogger("dynareporter.delivery_lead_dashboard")

router = APIRouter()

HIT_RATIO_TARGET = 30  # %


_DATE_RE = r"^\d{4}-\d{2}-\d{2}$"


@router.get(
    "/dashboard",
    response_model=DLDashboard,
    summary="Pełen Delivery Lead dashboard (team summary + team history)",
)
async def get_dashboard(
    current_user: CurrentUser,  # noqa: ARG001
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
    current_user: CurrentUser,  # noqa: ARG001
    db: AsyncSession = Depends(get_db),
    months: int = Query(default=6, ge=1, le=24),
) -> list[DLTrendRow]:
    """Zwraca trend Hit-Ratio per użytkownik za ostatnie `months` mies."""
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


@router.post(
    "/entry",
    summary="Admin upsert miesięcznego KPI DL (admin only)",
)
async def upsert_dl_entry(
    payload: DLUpsert,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Admin upsert wpisu DL KPI. ON CONFLICT (user_id, report_month)."""
    from app.models.user import UserRole

    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=403,
            detail="Tylko admin może modyfikować KPI DL",
        )

    # YYYY-MM → date(YYYY, MM, 1) — asyncpg wymaga `datetime.date` dla `date` column
    # (string "YYYY-MM-01" daje DataError: 'str' has no attribute 'toordinal').
    try:
        month_date = datetime.strptime(f"{payload.report_month}-01", "%Y-%m-%d").date()
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"report_month must be YYYY-MM (got '{payload.report_month}')",
        ) from exc
    sql = text(
        """
        INSERT INTO dr_kpi_delivery_lead (
            user_id, report_month, requests, placements, vacancies,
            open_requests, open_vacancies, created_at, updated_at
        ) VALUES (
            :user_id, :report_month, :requests, :placements, :vacancies,
            :open_requests, :open_vacancies, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
        )
        ON CONFLICT (user_id, report_month) DO UPDATE SET
            requests = EXCLUDED.requests,
            placements = EXCLUDED.placements,
            vacancies = EXCLUDED.vacancies,
            open_requests = EXCLUDED.open_requests,
            open_vacancies = EXCLUDED.open_vacancies,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """
    )
    result = await db.execute(
        sql,
        {
            "user_id": payload.user_id,
            "report_month": month_date,
            "requests": payload.requests,
            "placements": payload.placements,
            "vacancies": payload.vacancies,
            "open_requests": payload.open_requests,
            "open_vacancies": payload.open_vacancies,
        },
    )
    await db.commit()
    row = result.first()
    entry_id = row.id if row else None
    logger.info(
        "DL KPI entry upserted: id=%s user=%s month=%s placements=%s by admin=%s",
        entry_id,
        payload.user_id,
        payload.report_month,
        payload.placements,
        current_user.id,
    )
    return {"id": entry_id, "ok": True}
