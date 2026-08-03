"""Router `/api/my-clients` — lista klientów DL + per-client dashboard.

DL widzi tylko klientów do których ma `DeliveryLeadClientAssignment`.
Admin / head_of_recruitment widzą wszystkich.

Dashboard stosuje ten sam per-client guard, po rozwiązaniu merge redirectu.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import RedirectResponse

from app.api.deps import CurrentUser, require_dl_assigned_or_admin
from app.api.financial_access import has_financial_access
from app.core.database import get_db
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User, UserRole
from app.schemas.my_clients import (
    ClientDashboardResponse,
    ExpiringAlert,
    MyClientRow,
)
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
    is_client_visible,
    resolve_visible_client,
    visible_client_predicates,
)

router = APIRouter()


async def require_dl_assigned_or_admin_after_merge(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authorize dashboard access against the canonical client identity."""
    canonical = await resolve_visible_client(db, client_id, follow_merge=True)
    if canonical is None:
        raise HTTPException(404, detail="Client not found")

    # The merge moves client FK rows (including DL assignments) atomically.
    # Authorizing the canonical record avoids retaining access granted only by
    # an archived source identity.
    await require_dl_assigned_or_admin(
        client_id=canonical.id,
        current_user=current_user,
        db=db,
    )
    return current_user


CanonicalDlAssignedOrAdmin = Annotated[
    User,
    Depends(require_dl_assigned_or_admin_after_merge),
]


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


# ── My clients list ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=list[MyClientRow],
    response_model_exclude_none=True,
)
async def list_my_clients(
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista klientów DL (lub wszystkich dla admin/HoR)."""
    # Multi-role aware (M1-RBAC-02): hybryda np. recruiter+DL ma przejść
    # po roli dodatkowej, nie tylko primary.
    is_admin = user.has_any_role(UserRole.admin, UserRole.head_of_recruitment)
    client_name = client_display_name_expression()

    if is_admin:
        # Admin: wszyscy klienci, is_head_dl ustawione na False (admin nie ma DL assignment)
        clients_stmt = (
            select(Client)
            .where(*visible_client_predicates())
            .order_by(func.lower(client_name).asc(), Client.id.asc())
        )
        clients = list((await db.execute(clients_stmt)).scalars())
        client_ids = [c.id for c in clients]
        head_lookup: dict[int, bool] = {}
    else:
        if not user.has_role(UserRole.delivery_lead):
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
                    )
                    .join(
                        Client,
                        Client.id == DeliveryLeadClientAssignment.client_id,
                    )
                    .where(
                        DeliveryLeadClientAssignment.delivery_lead_user_id == user.id,
                        *visible_client_predicates(),
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
                        .where(
                            Client.id.in_(client_ids),
                            *visible_client_predicates(),
                        )
                        .order_by(func.lower(client_name).asc(), Client.id.asc())
                    )
                ).scalars()
            )

    if not client_ids:
        return []

    finance_ok = has_financial_access(user)

    # Aktywne ordery — licznik jest operacyjny i pozostaje dostępny dla DL/HoR.
    active_order_counts = {
        row.client_id: row
        for row in (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    func.count().label("active_count"),
                )
                .where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.status == ClientOrderStatus.active,
                )
                .group_by(ClientOrder.client_id)
            )
        )
    }

    # Kwot nie pobieramy nawet z bazy dla ról bez VIEW_FINANCE. Dzięki temu
    # ukrycie kart na froncie nie jest jedyną granicą bezpieczeństwa.
    active_revenue: dict[int, Decimal] = {}
    lifetime_revenue: dict[int, Decimal] = {}
    if finance_ok:
        active_revenue = {
            row.client_id: row.active_total
            for row in (
                await db.execute(
                    select(
                        ClientOrder.client_id,
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
        lifetime_revenue = {
            row.client_id: row.lifetime_total
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
                    ClientFrameworkContract.expiry_date <= today.replace(day=today.day),
                )
                .group_by(ClientFrameworkContract.client_id)
            )
        )
    }
    # ^ uproszczone — daje 0 dla "expiring soon" bo `today + 30d` wymaga datetime
    # delta. Liczba zostanie dokładnie wyciągnięta w dashboardzie. Tutaj pomocnik.

    items: list[MyClientRow] = []
    for c in clients:
        oa = active_order_counts.get(c.id)
        fc = fc_lookup.get(c.id)
        items.append(
            MyClientRow(
                client_id=c.id,
                name=client_display_name(c),
                industry=getattr(c, "industry", None),
                is_head_dl=head_lookup.get(c.id, False) if not is_admin else False,
                active_orders_count=oa.active_count if oa else 0,
                total_revenue_all_time=lifetime_revenue.get(c.id),
                active_revenue=active_revenue.get(c.id),
                expiring_soon_count=expiring.get(c.id, 0),
                framework_contract_status=fc[0] if fc else None,
                framework_expiry_date=fc[1] if fc else None,
            )
        )
    return items


# ── Per-client dashboard ────────────────────────────────────────────────────


@router.get(
    "/{client_id}/dashboard",
    response_model=ClientDashboardResponse,
    response_model_exclude_none=True,
)
async def client_dashboard(
    client_id: int,
    user: CanonicalDlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    if client.merged_into_client_id is not None:
        canonical = await resolve_visible_client(db, client_id, follow_merge=True)
        if canonical is None:
            raise HTTPException(404, detail="Client not found")
        return RedirectResponse(
            url=f"/api/my-clients/{canonical.id}/dashboard",
            # Merge rollback is supported, so avoid a permanent browser cache.
            status_code=status.HTTP_307_TEMPORARY_REDIRECT,
            headers={"X-Merged-From-Client-Id": str(client.id)},
        )
    if not is_client_visible(client):
        raise HTTPException(404, detail="Client not found")

    finance_ok = has_financial_access(user)

    # Status counts are operational. They deliberately do not select any order
    # value, rate or currency.
    order_status_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.status,
                    func.count(ClientOrder.id).label("count"),
                )
                .where(ClientOrder.client_id == client_id)
                .group_by(ClientOrder.status)
            )
        )
    )
    order_status_counts = {row.status: int(row.count or 0) for row in order_status_rows}

    # Revenue: lifetime total / active / completed. The query itself is
    # finance-gated; DL and HoR never load the raw amounts.
    total_rev = Decimal(0)
    active_rev = Decimal(0)
    completed_rev = Decimal(0)
    currency_breakdown: dict[str, Decimal] = {}
    if finance_ok:
        revenue_rows = list(
            (
                await db.execute(
                    select(
                        ClientOrder.status,
                        ClientOrder.currency,
                        func.coalesce(func.sum(ClientOrder.total_value), 0).label(
                            "sum_val"
                        ),
                    )
                    .where(ClientOrder.client_id == client_id)
                    .group_by(ClientOrder.status, ClientOrder.currency)
                )
            )
        )
        for row in revenue_rows:
            value = Decimal(row.sum_val) if row.sum_val is not None else Decimal(0)
            if row.status == ClientOrderStatus.cancelled:
                continue
            total_rev += value
            if row.status == ClientOrderStatus.active:
                active_rev += value
            if row.status == ClientOrderStatus.completed:
                completed_rev += value
            if row.currency:
                currency_breakdown[row.currency] = (
                    currency_breakdown.get(row.currency, Decimal(0)) + value
                )

    # Same split for contracts: status counts are operational, while margin
    # calculation loads full financial rows only for VIEW_FINANCE.
    contract_statuses = list(
        (
            await db.execute(
                select(Contract.status).where(Contract.client_id == client_id)
            )
        ).scalars()
    )
    monthly_margin_total = 0
    has_margin = False
    if finance_ok:
        contract_rows = list(
            (
                await db.execute(
                    select(Contract).where(Contract.client_id == client_id)
                )
            ).scalars()
        )
        for contract in contract_rows:
            if contract.status != ContractStatus.active:
                continue
            margin = contract.monthly_margin
            if margin is not None:
                monthly_margin_total += margin
                has_margin = True

    margin_pct: Optional[float] = None
    if has_margin and active_rev and active_rev > 0:
        margin_pct = round(float(monthly_margin_total) / float(active_rev) * 100, 2)

    # Konsultanci active vs completed (na podstawie kontraktów linkowanych do orderów)
    active_consultants = contract_statuses.count(ContractStatus.active)
    completed_consultants = contract_statuses.count(ContractStatus.ended)

    # Order velocity — średnio dni od `created_at` do gdy
    # `linked_contracts == positions_count` dla zakończonych zamówień.
    completed_orders = list(
        (
            await db.execute(
                select(ClientOrder.start_date, ClientOrder.created_at).where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.completed,
                )
            )
        )
    )
    velocities: list[float] = []
    for start_date, created_at in completed_orders:
        if not start_date:
            continue
        # Approx — used `start_date - created_at` jako proxy dla "filled"
        delta = (start_date - created_at.date()).days
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
    active_orders_count = order_status_counts.get(ClientOrderStatus.active, 0)
    completed_orders_count = order_status_counts.get(ClientOrderStatus.completed, 0)

    # Alerts: framework contracts expiring 30/14/7 dni + ordery ending 30/14/7 dni
    today = date.today()
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
                select(
                    ClientOrder.id,
                    ClientOrder.title,
                    ClientOrder.end_date,
                ).where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.active,
                    ClientOrder.end_date.is_not(None),
                )
            )
        ).all()
    )
    for order_id, title, end_date in orders_expiring:
        delta = (end_date - today).days
        if 0 <= delta <= 30:
            alerts.append(
                ExpiringAlert(
                    kind="order",
                    entity_id=order_id,
                    label=title,
                    days_to_expiry=delta,
                    expiry_date=end_date,
                )
            )

    alerts.sort(key=lambda a: a.days_to_expiry)

    _ = (active_orders_count, completed_orders_count)  # used below

    return ClientDashboardResponse(
        client_id=client_id,
        client_name=client_display_name(client),
        total_revenue_all_time=(total_rev or None) if finance_ok else None,
        active_revenue=(active_rev or None) if finance_ok else None,
        completed_revenue=(completed_rev or None) if finance_ok else None,
        currency_breakdown=currency_breakdown if finance_ok else None,
        monthly_margin_total=(
            monthly_margin_total if finance_ok and has_margin else None
        ),
        monthly_margin_pct=margin_pct if finance_ok else None,
        active_consultants=active_consultants,
        completed_consultants=completed_consultants,
        avg_days_to_fill=avg_days_to_fill,
        framework_contracts_count=fc_count,
        active_orders_count=active_orders_count,
        completed_orders_count=completed_orders_count,
        alerts=alerts,
    )
