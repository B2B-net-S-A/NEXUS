"""DynaReporter Rada Nadzorcza (Board) dashboard endpoint.

Port `/board` z artur-t-96/InfraReporter:
- monthly: 3 lata danych monthly P&L + per-client placement breakdown

Tylko admin/board_member może oglądać (top-secret financials).
"""

from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.dr_board_dashboard import (
    BoardMonthlyRow,
    BoardMonthlyUpsert,
    BoardPlacementClient,
)

router = APIRouter()

# Earliest report_month brany pod uwagę dla widoku Rady Nadzorczej.
# Dane sprzed 2024-01-01 to legacy DR — nie pokazujemy.
# Górną granicę liczymy dynamicznie z `CURRENT_DATE` (poprzednio
# hardcoded `'2026-12-01'` — quality check MEDIUM #6 silent empty 2027).
# MUST be `date` not `str` — asyncpg nie auto-coercuje stringów do date
# column type (DataError: 'str' object has no attribute 'toordinal').
BOARD_REPORT_START: date = date(2024, 1, 1)

# Rola umożliwiająca dostęp do widoku Board (financials).
# admin + delivery_lead + head_of_recruitment = managerski layer.
BOARD_ALLOWED_ROLES = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.head_of_recruitment,
)


def _require_board_access(current_user: User) -> None:
    """Multi-role aware — używa `has_any_role()` żeby uznać secondary
    role z `users.roles` JSONB (multi-role schema, migracja 0110).
    Bez tego user z primary=`recruiter` + secondary=`delivery_lead`
    byłby fałszywie odrzucany (quality check LOW #10)."""
    if not current_user.has_any_role(*BOARD_ALLOWED_ROLES):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do widoku Rady Nadzorczej",
        )


@router.get(
    "/monthly",
    response_model=list[BoardMonthlyRow],
    summary="36 miesięcy P&L (2024-2026) z per-client placement breakdown",
)
async def get_monthly(
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> list[BoardMonthlyRow]:
    """Zwraca miesięczne raporty Rady Nadzorczej."""
    _require_board_access(current_user)

    sql_report = text(
        """
        SELECT
            to_char(report_month, 'YYYY-MM') AS report_month,
            revenue::float AS revenue,
            consultant_costs::float AS consultant_costs,
            other_costs::float AS other_costs,
            active_consultants,
            departures,
            placements,
            avg_margin_per_hour::float AS avg_margin_per_hour,
            hit_ratio::float AS hit_ratio
        FROM dr_board_monthly_report
        WHERE report_month >= :start_date AND report_month <= CURRENT_DATE
        ORDER BY report_month ASC
        """
    )
    rows = (await db.execute(sql_report, {"start_date": BOARD_REPORT_START})).all()

    sql_clients = text(
        """
        SELECT
            to_char(report_month, 'YYYY-MM') AS report_month,
            client_name,
            placement_count
        FROM dr_board_placement_clients
        WHERE report_month >= :start_date AND report_month <= CURRENT_DATE
        ORDER BY report_month, placement_count DESC
        """
    )
    client_rows = (
        await db.execute(sql_clients, {"start_date": BOARD_REPORT_START})
    ).all()

    clients_by_month: dict[str, list[BoardPlacementClient]] = {}
    for c in client_rows:
        clients_by_month.setdefault(c.report_month, []).append(
            BoardPlacementClient(client_name=c.client_name, count=c.placement_count)
        )

    return [
        BoardMonthlyRow(
            report_month=r.report_month,
            revenue=r.revenue or 0.0,
            consultant_costs=r.consultant_costs or 0.0,
            other_costs=r.other_costs or 0.0,
            margin=(r.revenue or 0.0) - (r.consultant_costs or 0.0),
            profit=(r.revenue or 0.0)
            - (r.consultant_costs or 0.0)
            - (r.other_costs or 0.0),
            active_consultants=r.active_consultants or 0,
            departures=r.departures or 0,
            placements=r.placements or 0,
            avg_margin_per_hour=r.avg_margin_per_hour or 0.0,
            hit_ratio=r.hit_ratio or 0.0,
            placement_clients=clients_by_month.get(r.report_month, []),
        )
        for r in rows
    ]


@router.post(
    "/monthly",
    response_model=BoardMonthlyRow,
    status_code=status.HTTP_201_CREATED,
    summary="Upsert miesięcznego raportu Rady Nadzorczej + per-client placements",
)
async def upsert_monthly(
    payload: BoardMonthlyUpsert,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> BoardMonthlyRow:
    """Admin only — upsert miesięcznego board report. Idempotent ON CONFLICT."""
    _require_board_access(current_user)
    if current_user.role != UserRole.admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Tylko admin może modyfikować board data",
        )

    # YYYY-MM → date(YYYY, MM, 1) — asyncpg wymaga `datetime.date` dla kolumn typu
    # `date` (raw string "YYYY-MM-01" wywoła DataError: 'str' has no attribute 'toordinal').
    try:
        month_date = datetime.strptime(
            f"{payload.report_month}-01", "%Y-%m-%d"
        ).date()
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"report_month must be YYYY-MM (got '{payload.report_month}')",
        ) from exc

    # Upsert main report
    sql_upsert = text(
        """
        INSERT INTO dr_board_monthly_report (
            report_month, revenue, consultant_costs, other_costs,
            active_consultants, departures, placements,
            avg_margin_per_hour, hit_ratio, updated_at
        ) VALUES (
            :report_month, :revenue, :consultant_costs, :other_costs,
            :active_consultants, :departures, :placements,
            :avg_margin_per_hour, :hit_ratio, CURRENT_TIMESTAMP
        )
        ON CONFLICT (report_month) DO UPDATE SET
            revenue = EXCLUDED.revenue,
            consultant_costs = EXCLUDED.consultant_costs,
            other_costs = EXCLUDED.other_costs,
            active_consultants = EXCLUDED.active_consultants,
            departures = EXCLUDED.departures,
            placements = EXCLUDED.placements,
            avg_margin_per_hour = EXCLUDED.avg_margin_per_hour,
            hit_ratio = EXCLUDED.hit_ratio,
            updated_at = CURRENT_TIMESTAMP
        RETURNING id
        """
    )
    await db.execute(
        sql_upsert,
        {
            "report_month": month_date,
            "revenue": payload.revenue,
            "consultant_costs": payload.consultant_costs,
            "other_costs": payload.other_costs,
            "active_consultants": payload.active_consultants,
            "departures": payload.departures,
            "placements": payload.placements,
            "avg_margin_per_hour": payload.avg_margin_per_hour,
            "hit_ratio": payload.hit_ratio,
        },
    )

    # Re-set per-client placements (DELETE + INSERT pattern)
    await db.execute(
        text("DELETE FROM dr_board_placement_clients WHERE report_month = :m"),
        {"m": month_date},
    )
    for pc in payload.placement_clients:
        if pc.client_name and pc.count > 0:
            await db.execute(
                text(
                    """
                    INSERT INTO dr_board_placement_clients (
                        report_month, client_name, placement_count
                    ) VALUES (:m, :name, :cnt)
                    ON CONFLICT (report_month, client_name) DO UPDATE
                    SET placement_count = EXCLUDED.placement_count
                    """
                ),
                {"m": month_date, "name": pc.client_name.strip(), "cnt": pc.count},
            )

    await db.commit()

    return BoardMonthlyRow(
        report_month=payload.report_month,
        revenue=payload.revenue,
        consultant_costs=payload.consultant_costs,
        other_costs=payload.other_costs,
        margin=payload.revenue - payload.consultant_costs,
        profit=payload.revenue - payload.consultant_costs - payload.other_costs,
        active_consultants=payload.active_consultants,
        departures=payload.departures,
        placements=payload.placements,
        avg_margin_per_hour=payload.avg_margin_per_hour,
        hit_ratio=payload.hit_ratio,
        placement_clients=payload.placement_clients,
    )
