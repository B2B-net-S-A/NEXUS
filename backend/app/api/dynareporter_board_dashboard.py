"""DynaReporter Rada Nadzorcza (Board) dashboard endpoint.

Port `/board` z artur-t-96/InfraReporter:
- monthly: 3 lata danych monthly P&L + per-client placement breakdown

Tylko admin/board_member może oglądać (top-secret financials).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.dr_board_dashboard import BoardMonthlyRow, BoardPlacementClient

router = APIRouter()

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
        WHERE report_month >= '2024-01-01' AND report_month <= '2026-12-01'
        ORDER BY report_month ASC
        """
    )
    rows = (await db.execute(sql_report)).all()

    sql_clients = text(
        """
        SELECT
            to_char(report_month, 'YYYY-MM') AS report_month,
            client_name,
            placement_count
        FROM dr_board_placement_clients
        WHERE report_month >= '2024-01-01' AND report_month <= '2026-12-01'
        ORDER BY report_month, placement_count DESC
        """
    )
    client_rows = (await db.execute(sql_clients)).all()

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
