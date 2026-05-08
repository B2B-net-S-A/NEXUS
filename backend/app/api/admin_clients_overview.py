"""Router `/api/admin/clients-overview` — przekrojowe widoki dla admin/HoR.

GET `/` — wszyscy klienci z agregatami (rank po revenue desc).
GET `/by-dl` — KPI per DL (suma revenue z managed clients).
"""

from __future__ import annotations

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import HeadOfRecruitmentPlus
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
from app.models.user import User
from app.schemas.admin_clients_overview import DlKpiRow, OverviewRow

router = APIRouter()


@router.get("", response_model=list[OverviewRow])
async def clients_overview(
    _user: HeadOfRecruitmentPlus,
    db: AsyncSession = Depends(get_db),
):
    clients = list(
        (await db.execute(select(Client).order_by(Client.name))).scalars()
    )

    rev_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    ClientOrder.status,
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label("sum_val"),
                    func.count().label("cnt"),
                )
                .where(ClientOrder.status != ClientOrderStatus.cancelled)
                .group_by(ClientOrder.client_id, ClientOrder.status)
            )
        )
    )
    rev_lookup: dict[int, dict] = {}
    for r in rev_rows:
        slot = rev_lookup.setdefault(
            r.client_id, {"total": Decimal(0), "active": Decimal(0), "active_count": 0}
        )
        v = Decimal(r.sum_val) if r.sum_val is not None else Decimal(0)
        slot["total"] += v
        if r.status == ClientOrderStatus.active:
            slot["active"] += v
            slot["active_count"] = r.cnt

    head_dl_rows = list(
        (
            await db.execute(
                select(
                    DeliveryLeadClientAssignment.client_id,
                    User.id,
                    User.name,
                )
                .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
                .where(DeliveryLeadClientAssignment.is_head.is_(True))
            )
        )
    )
    head_dl_lookup: dict[int, tuple[int, str]] = {
        r.client_id: (r.id, r.name) for r in head_dl_rows
    }

    fc_rows = list(
        (
            await db.execute(
                select(
                    ClientFrameworkContract.client_id,
                    ClientFrameworkContract.status,
                    ClientFrameworkContract.expiry_date,
                )
                .where(
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
    fc_lookup: dict[int, tuple[str, object]] = {}
    for r in fc_rows:
        if r.client_id not in fc_lookup:
            fc_lookup[r.client_id] = (r.status.value, r.expiry_date)

    margin_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    Contract.rate_client,
                    Contract.rate_candidate,
                    Contract.rate_unit,
                    Contract.billing_hours_per_month,
                    Contract.status,
                )
                .join(ClientOrderContract, ClientOrderContract.order_id == ClientOrder.id)
                .join(Contract, Contract.id == ClientOrderContract.contract_id)
                .where(Contract.status == ContractStatus.active)
            )
        )
    )
    margin_lookup: dict[int, int] = {}
    consultants_lookup: dict[int, int] = {}
    for r in margin_rows:
        consultants_lookup[r.client_id] = consultants_lookup.get(r.client_id, 0) + 1
        if r.rate_client is None or r.rate_candidate is None:
            continue
        diff = r.rate_client - r.rate_candidate
        if r.rate_unit == "daily":
            monthly = diff * 22
        elif r.rate_unit == "hourly":
            monthly = diff * (r.billing_hours_per_month or 160)
        else:
            monthly = diff
        margin_lookup[r.client_id] = margin_lookup.get(r.client_id, 0) + monthly

    items: list[OverviewRow] = []
    for c in clients:
        rev = rev_lookup.get(c.id, {"total": None, "active": None, "active_count": 0})
        head = head_dl_lookup.get(c.id)
        fc = fc_lookup.get(c.id)
        items.append(
            OverviewRow(
                client_id=c.id,
                name=c.name,
                industry=getattr(c, "industry", None),
                head_dl_id=head[0] if head else None,
                head_dl_name=head[1] if head else None,
                total_revenue_all_time=rev["total"] or None,
                active_revenue=rev["active"] or None,
                monthly_margin_total=margin_lookup.get(c.id),
                active_orders_count=rev["active_count"],
                active_consultants=consultants_lookup.get(c.id, 0),
                framework_status=fc[0] if fc else None,
                framework_expiry_date=fc[1] if fc else None,
            )
        )

    items.sort(
        key=lambda r: (r.total_revenue_all_time or 0),
        reverse=True,
    )
    return items


@router.get("/by-dl", response_model=list[DlKpiRow])
async def kpi_by_dl(
    _user: HeadOfRecruitmentPlus,
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
                ).join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
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

    # Per-DL agregaty: revenue, active orders, marża
    items: list[DlKpiRow] = []
    for dl_id, slot in dl_clients.items():
        client_ids = slot["client_ids"]
        if not client_ids:
            continue

        rev = (
            await db.execute(
                select(
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label("total"),
                    func.coalesce(
                        func.sum(
                            case(
                                (ClientOrder.status == ClientOrderStatus.active, ClientOrder.total_value),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("active"),
                    func.coalesce(
                        func.sum(
                            case(
                                (ClientOrder.status == ClientOrderStatus.active, 1),
                                else_=0,
                            )
                        ),
                        0,
                    ).label("active_orders_cnt"),
                ).where(
                    ClientOrder.client_id.in_(client_ids),
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
            )
        ).one()

        margin_rows_dl = list(
            (
                await db.execute(
                    select(
                        Contract.rate_client,
                        Contract.rate_candidate,
                        Contract.rate_unit,
                        Contract.billing_hours_per_month,
                    )
                    .join(ClientOrderContract, ClientOrderContract.contract_id == Contract.id)
                    .join(ClientOrder, ClientOrder.id == ClientOrderContract.order_id)
                    .where(
                        ClientOrder.client_id.in_(client_ids),
                        Contract.status == ContractStatus.active,
                    )
                )
            )
        )
        active_consultants = len(margin_rows_dl)
        margin_total = 0
        has_margin = False
        for r in margin_rows_dl:
            if r.rate_client is None or r.rate_candidate is None:
                continue
            diff = r.rate_client - r.rate_candidate
            if r.rate_unit == "daily":
                monthly = diff * 22
            elif r.rate_unit == "hourly":
                monthly = diff * (r.billing_hours_per_month or 160)
            else:
                monthly = diff
            margin_total += monthly
            has_margin = True

        items.append(
            DlKpiRow(
                dl_user_id=dl_id,
                dl_name=slot["name"],
                dl_email=slot["email"],
                managed_clients_count=len(client_ids),
                head_clients_count=slot["head_count"],
                total_revenue=Decimal(rev.total) if rev.total else None,
                active_revenue=Decimal(rev.active) if rev.active else None,
                monthly_margin_total=margin_total if has_margin else None,
                active_orders_count=int(rev.active_orders_cnt or 0),
                active_consultants=active_consultants,
            )
        )
    items.sort(key=lambda r: (r.total_revenue or 0), reverse=True)
    return items
