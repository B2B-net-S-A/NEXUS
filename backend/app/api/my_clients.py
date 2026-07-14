"""Router `/api/my-clients` — lista klientów DL + per-client dashboard.

DL widzi tylko klientów do których ma `DeliveryLeadClientAssignment`.
Admin / head_of_recruitment widzą wszystkich.

Dashboard endpoint chroniony przez `DlAssignedOrAdmin` (per-client check).
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
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
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import UserRole
from app.schemas.my_clients import (
    ClientDashboardResponse,
    ExpiringAlert,
    MyClientRow,
)
from app.services.fx_service import convert_to_pln, fx_age_days

router = APIRouter()


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


async def _to_pln_strict(
    db: AsyncSession, amount: Decimal | int | None, currency: str | None
) -> Decimal:
    """Convert a financial aggregate without ever assuming an unknown FX=1."""

    cur = (currency or "PLN").upper()
    if cur != "PLN" and await fx_age_days(db, cur) is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Missing FX rate for {cur}; client finance is unavailable",
        )
    return await convert_to_pln(db, Decimal(amount or 0), cur)


# ── My clients list ─────────────────────────────────────────────────────────


@router.get("", response_model=list[MyClientRow])
async def list_my_clients(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista finansowa klientów DL (lub wszystkich dla admina).

    HoR używa operacyjnego analytics API bez stawek i wartości finansowych.
    """
    is_admin = user.has_role(UserRole.admin)

    if is_admin:
        # Admin: wszyscy klienci, is_head_dl ustawione na False (admin nie ma DL assignment)
        clients_stmt = select(Client).order_by(Client.name)
        clients = list((await db.execute(clients_stmt)).scalars())
        client_ids = [c.id for c in clients]
        head_lookup: dict[int, bool] = {}
    else:
        if not user.has_role(UserRole.delivery_lead):
            raise HTTPException(
                403,
                detail="Only Delivery Leads or admin can view client finance",
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
    orders_agg: dict[int, dict[str, Decimal | int]] = {}
    active_order_rows = await db.execute(
        select(
            ClientOrder.client_id,
            ClientOrder.currency,
            func.count(ClientOrder.id).label("active_count"),
            func.coalesce(func.sum(ClientOrder.total_value), 0).label("active_total"),
        )
        .where(
            ClientOrder.client_id.in_(client_ids),
            ClientOrder.status == ClientOrderStatus.active,
        )
        .group_by(ClientOrder.client_id, ClientOrder.currency)
    )
    for row in active_order_rows:
        bucket = orders_agg.setdefault(
            row.client_id, {"active_count": 0, "active_total": Decimal(0)}
        )
        bucket["active_count"] = int(bucket["active_count"]) + int(row.active_count)
        bucket["active_total"] = Decimal(bucket["active_total"]) + await _to_pln_strict(
            db, row.active_total, row.currency
        )
    # Total revenue lifetime — wszystkie ordery non-cancelled
    lifetime_agg: dict[int, Decimal] = {}
    lifetime_rows = await db.execute(
        select(
            ClientOrder.client_id,
            ClientOrder.currency,
            func.coalesce(func.sum(ClientOrder.total_value), 0).label("lifetime_total"),
        )
        .where(
            ClientOrder.client_id.in_(client_ids),
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
        .group_by(ClientOrder.client_id, ClientOrder.currency)
    )
    for row in lifetime_rows:
        lifetime_agg[row.client_id] = lifetime_agg.get(
            row.client_id, Decimal(0)
        ) + await _to_pln_strict(db, row.lifetime_total, row.currency)

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
                    ClientFrameworkContract.expiry_date >= today,
                    ClientFrameworkContract.expiry_date < today + timedelta(days=31),
                )
                .group_by(ClientFrameworkContract.client_id)
            )
        )
    }
    order_expiring = {
        row.client_id: row.cnt
        for row in (
            await db.execute(
                select(ClientOrder.client_id, func.count(ClientOrder.id).label("cnt"))
                .where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.status == ClientOrderStatus.active,
                    ClientOrder.end_date.is_not(None),
                    ClientOrder.end_date >= today,
                    ClientOrder.end_date < today + timedelta(days=31),
                )
                .group_by(ClientOrder.client_id)
            )
        )
    }

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
                active_orders_count=int(oa["active_count"]) if oa else 0,
                total_revenue_all_time=la,
                active_revenue=Decimal(oa["active_total"]) if oa else None,
                expiring_soon_count=(
                    int(expiring.get(c.id, 0)) + int(order_expiring.get(c.id, 0))
                ),
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
    if not _user.has_any_role(UserRole.admin, UserRole.delivery_lead):
        raise HTTPException(
            403, detail="Client finance requires admin or delivery_lead"
        )
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
                    func.count(ClientOrder.id).label("order_count"),
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label(
                        "sum_val"
                    ),
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
        original_value = Decimal(r.sum_val) if r.sum_val is not None else Decimal(0)
        if r.status == ClientOrderStatus.cancelled:
            continue
        v = await _to_pln_strict(db, original_value, r.currency)
        total_rev += v
        if r.status == ClientOrderStatus.active:
            active_rev += v
        if r.status == ClientOrderStatus.completed:
            completed_rev += v
        if r.currency:
            currency_breakdown[r.currency] = (
                currency_breakdown.get(r.currency, Decimal(0)) + original_value
            )

    # Margin z aktywnych Contractów klienta (po refactorze 2026-05-11:
    # Contract 1:N Order, więc Contract.client_id daje wszystkie kontraktory).
    today = date.today()
    contract_rows = list(
        (
            await db.execute(select(Contract).where(Contract.client_id == client_id))
        ).scalars()
    )
    active_contract_rows = [
        contract
        for contract in contract_rows
        if contract.status in (ContractStatus.active, ContractStatus.ending)
        and contract.start_date is not None
        and contract.start_date <= today
        and (contract.end_date is None or contract.end_date >= today)
    ]
    monthly_margin_total = Decimal(0)
    monthly_revenue_total = Decimal(0)
    has_margin = False
    for contract in active_contract_rows:
        m = contract.monthly_margin
        if m is not None:
            monthly_margin_total += await _to_pln_strict(db, m, contract.currency)
            has_margin = True
        if contract.monthly_rate_client is not None:
            monthly_revenue_total += await _to_pln_strict(
                db, contract.monthly_rate_client, contract.currency
            )

    margin_pct: Optional[float] = None
    if has_margin and monthly_revenue_total > 0:
        margin_pct = round(
            float(monthly_margin_total / monthly_revenue_total * Decimal(100)), 2
        )

    # Konsultanci active vs completed (na podstawie kontraktów linkowanych do orderów)
    active_candidate_ids = {c.candidate_id for c in active_contract_rows}
    active_consultants = len(active_candidate_ids)
    completed_consultants = len(
        {
            c.candidate_id
            for c in contract_rows
            if c.status == ContractStatus.ended
            and c.candidate_id not in active_candidate_ids
        }
    )

    # Order velocity is based only on the audited first activation timestamp.
    # We deliberately do not infer missing history from start_date.
    completed_orders = list(
        (
            await db.execute(
                select(ClientOrder).where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.completed,
                )
            )
        ).scalars()
    )
    velocities = [
        (o.filled_at - o.created_at).total_seconds() / 86400
        for o in completed_orders
        if o.filled_at is not None and o.filled_at >= o.created_at
    ]
    # Any untraceable historical row makes the aggregate partial, so keep the
    # legacy field NULL rather than presenting a selective average as complete.
    avg_days_to_fill = (
        round(sum(velocities) / len(velocities), 1)
        if completed_orders and len(velocities) == len(completed_orders)
        else None
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
        int(r.order_count) for r in rev_rows if r.status == ClientOrderStatus.active
    )
    completed_orders_count = sum(
        int(r.order_count) for r in rev_rows if r.status == ClientOrderStatus.completed
    )

    # Alerts: framework contracts expiring 30/14/7 dni + ordery ending 30/14/7 dni
    alerts: list[ExpiringAlert] = []

    fc_expiring = list(
        (
            await db.execute(
                select(ClientFrameworkContract).where(
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
                select(ClientOrder).where(
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
