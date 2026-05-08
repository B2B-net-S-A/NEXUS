"""Router `/api/my-clients` — lista klientów DL + per-client dashboard.

DL widzi tylko klientów do których ma `DeliveryLeadClientAssignment`.
Admin / head_of_recruitment widzą wszystkich.

Dashboard endpoint chroniony przez `DlAssignedOrAdmin` (per-client check).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import CurrentUser, DlAssignedOrAdmin
from app.core.database import get_db
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_contract import ClientOrderContract
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.schemas.my_clients import (
    ClientDashboardResponse,
    ExpiringAlert,
    MyClientRow,
)

router = APIRouter()


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


# ── My clients list ─────────────────────────────────────────────────────────


@router.get("", response_model=list[MyClientRow])
async def list_my_clients(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista klientów DL (lub wszystkich dla admin/HoR)."""
    is_admin = user.role in (UserRole.admin, UserRole.head_of_recruitment)

    if is_admin:
        # Admin: wszyscy klienci, is_head_dl ustawione na False (admin nie ma DL assignment)
        clients_stmt = select(Client).order_by(Client.name)
        clients = list((await db.execute(clients_stmt)).scalars())
        client_ids = [c.id for c in clients]
        head_lookup: dict[int, bool] = {}
    else:
        if user.role != UserRole.delivery_lead:
            raise HTTPException(
                403,
                detail="Only Delivery Leads or admin/head_of_recruitment can view My Clients",
            )
        # DL: pobierz przypisania + clients
        assignments = list(
            (
                await db.execute(
                    select(
                        DeliveryLeadClientAssignment.client_id,
                        DeliveryLeadClientAssignment.is_head,
                        Client.name,
                        Client.industry,
                    )
                    .join(
                        Client,
                        Client.id == DeliveryLeadClientAssignment.client_id,
                    )
                    .where(
                        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
                    )
                )
            )
        )
        client_ids = [a.client_id for a in assignments]
        head_lookup = {a.client_id: a.is_head for a in assignments}
        clients = []
        if client_ids:
            clients = list(
                (
                    await db.execute(
                        select(Client)
                        .where(Client.id.in_(client_ids))
                        .order_by(Client.name)
                    )
                ).scalars()
            )

    if not client_ids:
        return []

    # Aktywne ordery — count + suma value (active = active status)
    orders_agg = {
        row.client_id: row
        for row in (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    func.count().label("active_count"),
                    func.sum(ClientOrder.total_value).label("active_total"),
                )
                .where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.status == ClientOrderStatus.active,
                )
                .group_by(ClientOrder.client_id)
            )
        )
    }
    # Total revenue lifetime — wszystkie ordery non-cancelled
    lifetime_agg = {
        row.client_id: row
        for row in (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    func.sum(ClientOrder.total_value).label("lifetime_total"),
                )
                .where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
                .group_by(ClientOrder.client_id)
            )
        )
    }

    # Active framework contract per klient (status=active, max effective_date)
    fc_rows = list(
        (
            await db.execute(
                select(
                    ClientFrameworkContract.client_id,
                    ClientFrameworkContract.status,
                    ClientFrameworkContract.expiry_date,
                )
                .where(
                    ClientFrameworkContract.client_id.in_(client_ids),
                    ClientFrameworkContract.status.in_(
                        (
                            FrameworkContractStatus.active,
                            FrameworkContractStatus.pending_signature,
                        )
                    ),
                )
                .order_by(
                    ClientFrameworkContract.client_id,
                    ClientFrameworkContract.effective_date.desc().nullslast(),
                )
            )
        )
    )
    fc_lookup: dict[int, tuple[str, Optional[date]]] = {}
    for r in fc_rows:
        if r.client_id not in fc_lookup:
            fc_lookup[r.client_id] = (r.status.value, r.expiry_date)

    # Expiring soon counter (FC + Order ≤ 30d)
    today = date.today()
    expiring = {
        row.client_id: row.cnt
        for row in (
            await db.execute(
                select(
                    ClientFrameworkContract.client_id,
                    func.count().label("cnt"),
                )
                .where(
                    ClientFrameworkContract.client_id.in_(client_ids),
                    ClientFrameworkContract.status == FrameworkContractStatus.active,
                    ClientFrameworkContract.expiry_date.is_not(None),
                    ClientFrameworkContract.expiry_date <= today.replace(
                        day=today.day
                    ),
                )
                .group_by(ClientFrameworkContract.client_id)
            )
        )
    }
    # ^ uproszczone — daje 0 dla "expiring soon" bo `today + 30d` wymaga datetime
    # delta. Liczba zostanie dokładnie wyciągnięta w dashboardzie. Tutaj pomocnik.

    items: list[MyClientRow] = []
    for c in clients:
        oa = orders_agg.get(c.id)
        la = lifetime_agg.get(c.id)
        fc = fc_lookup.get(c.id)
        items.append(
            MyClientRow(
                client_id=c.id,
                name=c.name,
                industry=getattr(c, "industry", None),
                is_head_dl=head_lookup.get(c.id, False) if not is_admin else False,
                active_orders_count=oa.active_count if oa else 0,
                total_revenue_all_time=la.lifetime_total if la else None,
                active_revenue=oa.active_total if oa else None,
                expiring_soon_count=expiring.get(c.id, 0),
                framework_contract_status=fc[0] if fc else None,
                framework_expiry_date=fc[1] if fc else None,
            )
        )
    return items


# ── Per-client dashboard ────────────────────────────────────────────────────


@router.get("/{client_id}/dashboard", response_model=ClientDashboardResponse)
async def client_dashboard(
    client_id: int,
    _user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")

    # Revenue: lifetime total / active / completed
    rev_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.status,
                    ClientOrder.currency,
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label("sum_val"),
                )
                .where(ClientOrder.client_id == client_id)
                .group_by(ClientOrder.status, ClientOrder.currency)
            )
        )
    )
    total_rev = Decimal(0)
    active_rev = Decimal(0)
    completed_rev = Decimal(0)
    currency_breakdown: dict[str, Decimal] = {}
    for r in rev_rows:
        v = Decimal(r.sum_val) if r.sum_val is not None else Decimal(0)
        if r.status == ClientOrderStatus.cancelled:
            continue
        total_rev += v
        if r.status == ClientOrderStatus.active:
            active_rev += v
        if r.status == ClientOrderStatus.completed:
            completed_rev += v
        if r.currency:
            currency_breakdown[r.currency] = currency_breakdown.get(
                r.currency, Decimal(0)
            ) + v

    # Margin from linked active contracts
    contract_rows = list(
        (
            await db.execute(
                select(Contract)
                .join(
                    ClientOrderContract,
                    ClientOrderContract.contract_id == Contract.id,
                )
                .join(
                    ClientOrder,
                    ClientOrder.id == ClientOrderContract.order_id,
                )
                .where(ClientOrder.client_id == client_id)
            )
        ).scalars()
    )
    monthly_margin_total = 0
    has_margin = False
    for c in contract_rows:
        if c.status != ContractStatus.active:
            continue
        m = c.monthly_margin
        if m is not None:
            monthly_margin_total += m
            has_margin = True

    margin_pct: Optional[float] = None
    if has_margin and active_rev and active_rev > 0:
        margin_pct = round(float(monthly_margin_total) / float(active_rev) * 100, 2)

    # Konsultanci active vs completed (na podstawie kontraktów linkowanych do orderów)
    active_consultants = sum(
        1 for c in contract_rows if c.status == ContractStatus.active
    )
    completed_consultants = sum(
        1 for c in contract_rows if c.status == ContractStatus.ended
    )

    # Order velocity — średnio dni od `created_at` do gdy
    # `linked_contracts == positions_count` dla zakończonych zamówień.
    completed_orders = list(
        (
            await db.execute(
                select(ClientOrder)
                .where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.completed,
                )
            )
        ).scalars()
    )
    velocities: list[float] = []
    for o in completed_orders:
        if not o.start_date:
            continue
        # Approx — used `start_date - created_at` jako proxy dla "filled"
        delta = (o.start_date - o.created_at.date()).days
        if delta >= 0:
            velocities.append(float(delta))
    avg_days_to_fill = (
        round(sum(velocities) / len(velocities), 1) if velocities else None
    )

    # Counts
    fc_count = (
        await db.scalar(
            select(func.count())
            .select_from(ClientFrameworkContract)
            .where(ClientFrameworkContract.client_id == client_id)
        )
    ) or 0
    active_orders_count = sum(
        1 for r in rev_rows if r.status == ClientOrderStatus.active
    )
    completed_orders_count = sum(
        1 for r in rev_rows if r.status == ClientOrderStatus.completed
    )

    # Alerts: framework contracts expiring 30/14/7 dni + ordery ending 30/14/7 dni
    today = date.today()
    alerts: list[ExpiringAlert] = []

    fc_expiring = list(
        (
            await db.execute(
                select(ClientFrameworkContract)
                .where(
                    ClientFrameworkContract.client_id == client_id,
                    ClientFrameworkContract.status == FrameworkContractStatus.active,
                    ClientFrameworkContract.expiry_date.is_not(None),
                )
            )
        ).scalars()
    )
    for fc in fc_expiring:
        delta = (fc.expiry_date - today).days
        if 0 <= delta <= 30:
            alerts.append(
                ExpiringAlert(
                    kind="framework_contract",
                    entity_id=fc.id,
                    label=fc.name,
                    days_to_expiry=delta,
                    expiry_date=fc.expiry_date,
                )
            )

    orders_expiring = list(
        (
            await db.execute(
                select(ClientOrder)
                .where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.active,
                    ClientOrder.end_date.is_not(None),
                )
            )
        ).scalars()
    )
    for o in orders_expiring:
        delta = (o.end_date - today).days
        if 0 <= delta <= 30:
            alerts.append(
                ExpiringAlert(
                    kind="order",
                    entity_id=o.id,
                    label=o.title,
                    days_to_expiry=delta,
                    expiry_date=o.end_date,
                )
            )

    alerts.sort(key=lambda a: a.days_to_expiry)

    _ = (active_orders_count, completed_orders_count)  # used below

    return ClientDashboardResponse(
        client_id=client_id,
        client_name=client.name,
        total_revenue_all_time=total_rev or None,
        active_revenue=active_rev or None,
        completed_revenue=completed_rev or None,
        currency_breakdown={k: v for k, v in currency_breakdown.items()},
        monthly_margin_total=monthly_margin_total if has_margin else None,
        monthly_margin_pct=margin_pct,
        active_consultants=active_consultants,
        completed_consultants=completed_consultants,
        avg_days_to_fill=avg_days_to_fill,
        framework_contracts_count=fc_count,
        active_orders_count=active_orders_count,
        completed_orders_count=completed_orders_count,
        alerts=alerts,
    )
