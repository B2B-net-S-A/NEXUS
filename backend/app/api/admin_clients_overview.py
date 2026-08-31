"""Router `/api/admin/clients-overview` — przekrojowe widoki finansowe.

GET `/` — wszyscy klienci z agregatami (rank po revenue desc).
GET `/by-dl` — KPI per DL (suma revenue z managed clients).

Audyt M7 PR-01 (P0.1): oba endpointy zwracają lifetime/active revenue i marżę
per klient oraz per DL — to dane ``VIEW_FINANCE``. Head of recruitment NIE ma
tej capability (analytics/capabilities.py §4.3), dlatego guard zszedł z
``HeadOfRecruitmentPlus`` na globalny read dla Admin/Finance (przekrój wszystkich
klientów i DL to widok zarządczy; per-client scope dla DL to osobna decyzja —
§31/Fala C).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.financial_access import FinanceReadUser
from app.core.database import get_db
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.schemas.admin_clients_overview import DlKpiRow, OverviewRow
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.contractor_identity import summarize_active_contracts
from app.services.insights_clients import (
    LIVE_CONTRACT_STATUSES,
    compute_client_ranking,
    margin_lookup_pln,
)
from app.services.order_revenue import order_revenue_rows_to_pln

router = APIRouter()


# Ranking klientów i marża liczą się w ``app/services/insights_clients.py`` —
# ta sama funkcja zasila `/api/insights/clients/ranking`. Dwie kopie tego SQL
# rozjeżdżałyby się cicho, bo obie odpowiedzi wyglądają wiarygodnie i nikt nie
# kładzie ich obok siebie. Guard (``FinanceReadUser``) i kształt odpowiedzi
# (``OverviewRow``) zostają tutaj i NIE zmieniają się — /insights ma własny
# router na ``CurrentUser``, bo ten endpoint jest współdzielony z portalem DL.
_LIVE_CONTRACT_STATUSES = LIVE_CONTRACT_STATUSES
_margin_lookup_pln = margin_lookup_pln


@router.get("", response_model=list[OverviewRow])
async def clients_overview(
    _user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    rows = await compute_client_ranking(db, on=date.today())
    return [OverviewRow.model_validate(row) for row in rows]


@router.get("/by-dl", response_model=list[DlKpiRow])
async def kpi_by_dl(
    _user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Leaderboard DL — agregaty po klientach gdzie DL ma assignment."""
    # Wszystkie assignmenty (każdy DL × każdy klient)
    rows = list(
        (
            await db.execute(
                select(
                    DeliveryLeadClientAssignment.delivery_lead_user_id,
                    DeliveryLeadClientAssignment.client_id,
                    DeliveryLeadClientAssignment.is_head,
                    User.name,
                    User.email,
                ).join(
                    User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id
                )
            )
        )
    )

    # Group przez DL
    dl_clients: dict[int, dict] = {}
    for r in rows:
        slot = dl_clients.setdefault(
            r.delivery_lead_user_id,
            {
                "name": r.name,
                "email": r.email,
                "client_ids": [],
                "head_count": 0,
            },
        )
        slot["client_ids"].append(r.client_id)
        if r.is_head:
            slot["head_count"] += 1

    if not dl_clients:
        return []

    all_client_ids = {
        client_id for slot in dl_clients.values() for client_id in slot["client_ids"]
    }
    dl_revenue_rows = list(
        await db.execute(
            select(
                ClientOrder.client_id,
                ClientOrder.status,
                ClientOrder.currency,
                func.coalesce(func.sum(ClientOrder.total_value), 0).label("sum_val"),
                func.count().label("cnt"),
            )
            .where(ClientOrder.client_id.in_(all_client_ids))
            .group_by(
                ClientOrder.client_id,
                ClientOrder.status,
                ClientOrder.currency,
            )
        )
    )
    dl_revenue_lookup, dl_revenue_incomplete = await order_revenue_rows_to_pln(
        db, dl_revenue_rows, date.today()
    )
    active_orders_by_client: dict[int, int] = {}
    for row in dl_revenue_rows:
        if row.status == ClientOrderStatus.active:
            active_orders_by_client[row.client_id] = active_orders_by_client.get(
                row.client_id, 0
            ) + int(row.cnt or 0)

    # Per-DL agregaty: revenue, active orders, marża
    items: list[DlKpiRow] = []
    for dl_id, slot in dl_clients.items():
        client_ids = slot["client_ids"]
        if not client_ids:
            continue

        revenue_complete = not any(
            client_id in dl_revenue_incomplete for client_id in client_ids
        )
        revenue_total = sum(
            (
                dl_revenue_lookup.get(client_id, {}).get("total", Decimal("0"))
                for client_id in client_ids
            ),
            start=Decimal("0"),
        )
        active_revenue = sum(
            (
                dl_revenue_lookup.get(client_id, {}).get("active", Decimal("0"))
                for client_id in client_ids
            ),
            start=Decimal("0"),
        )
        active_orders_count = sum(
            active_orders_by_client.get(client_id, 0) for client_id in client_ids
        )

        # Refactor 2026-05-11: Contract.client_id daje wszystkich kontraktorów
        # tego DL (bez join'a do Order).
        margin_rows_dl = list(
            (
                await db.execute(
                    select(Contract)
                    .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
                    .where(
                        Contract.client_id.in_(client_ids),
                        Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                    )
                )
            ).scalars()
        )
        active_headcount = summarize_active_contracts(margin_rows_dl)
        today = date.today()
        margin_lookup_dl, incomplete_margin_clients = await _margin_lookup_pln(
            db, margin_rows_dl, today
        )
        margin_total = sum(margin_lookup_dl.values(), start=Decimal("0"))
        has_margin = bool(margin_lookup_dl) and not incomplete_margin_clients

        items.append(
            DlKpiRow(
                dl_user_id=dl_id,
                dl_name=slot["name"],
                dl_email=slot["email"],
                managed_clients_count=len(client_ids),
                head_clients_count=slot["head_count"],
                total_revenue=(revenue_total or None) if revenue_complete else None,
                active_revenue=(active_revenue or None) if revenue_complete else None,
                monthly_margin_total=margin_total if has_margin else None,
                active_orders_count=active_orders_count,
                active_consultants=active_headcount.contractors,
                active_contracts=active_headcount.active_contracts,
            )
        )
    items.sort(key=lambda r: r.total_revenue or 0, reverse=True)
    return items
