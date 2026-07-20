"""DynaReporter Rada Nadzorcza (Board) dashboard endpoint.

Port `/board` z artur-t-96/InfraReporter:
- monthly: 3 lata danych monthly P&L + per-client placement breakdown

Tylko admin/board_member może oglądać (top-secret financials).

2026-07-20: usunięte trasy zapisu (POST upsert /monthly, DELETE /monthly/{m}) —
ręczne wprowadzanie statystyk wygaszone, NEXUS liczy te liczby sam
(patrz /insights). GET-y zostają dla widoków historycznych.
"""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.deps import CurrentUser
from app.core.database import get_db
from app.models.user import User
from app.schemas.dr_board_dashboard import BoardMonthlyRow, BoardPlacementClient

router = APIRouter()

# Earliest report_month brany pod uwagę dla widoku Rady Nadzorczej.
# Dane sprzed 2024-01-01 to legacy DR — nie pokazujemy.
# Górną granicę liczymy dynamicznie z `CURRENT_DATE` (poprzednio
# hardcoded `'2026-12-01'` — quality check MEDIUM #6 silent empty 2027).
# MUST be `date` not `str` — asyncpg nie auto-coercuje stringów do date
# column type (DataError: 'str' object has no attribute 'toordinal').
BOARD_REPORT_START: date = date(2024, 1, 1)


def _require_board_access(current_user: User) -> None:
    """Audyt M7 PR-01 (P0.1): widok Rady Nadzorczej to pełny P&L (revenue,
    koszty, profit) → wymaga ``VIEW_FINANCE``. Head of recruitment NIE ma tej
    capability (patrz analytics/capabilities.py §4.3), więc traci dostęp do
    finansów zarządczych — ujednolica z ``dynareporter_board.py``, który już
    gate'uje przez VIEW_FINANCE. Wcześniej ``BOARD_ALLOWED_ROLES`` wpuszczało
    HoR do P&L (split-brain względem macierzy capability).

    Multi-role aware: ``user_has_capability`` liczy unię z ``get_all_roles()``,
    więc secondary role (np. recruiter+delivery_lead) są uwzględniane."""
    if not user_has_capability(current_user, AnalyticsCapability.VIEW_FINANCE):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Brak uprawnień do widoku Rady Nadzorczej (wymaga VIEW_FINANCE)",
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
