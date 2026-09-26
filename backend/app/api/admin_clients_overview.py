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

from decimal import Decimal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.financial_access import FinanceReadUser
from app.core.database import get_db
from app.models.client_order import ClientOrderStatus
from app.models.contract import Contract
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.schemas.admin_clients_overview import DlKpiRow, OverviewRow
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.contractor_identity import (
    load_current_contracts,
    summarize_active_contracts,
)
from app.services.insights_clients import (
    LIVE_CONTRACT_STATUSES,
    compute_client_ranking,
    margin_lookup_pln,
)
from app.services.order_revenue import (
    client_order_value_rows,
    order_revenue_rows_to_pln,
)
from app.core.scheduling import business_today

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
    rows = await compute_client_ranking(db, on=business_today())
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
    # Ta sama reguła wartości i liczby zamówień co Analityka klienta:
    # zamówienie MD/kosztowe = jedno zamówienie z wartością grupy, bez
    # szkiców (audyt 24.09.2026, W1).
    dl_revenue_rows = await client_order_value_rows(db, all_client_ids)
    dl_revenue_lookup, dl_revenue_incomplete = await order_revenue_rows_to_pln(
        db, dl_revenue_rows, business_today()
    )
    active_orders_by_client: dict[int, int] = {}
    for row in dl_revenue_rows:
        if row.status == ClientOrderStatus.active:
            active_orders_by_client[row.client_id] = active_orders_by_client.get(
                row.client_id, 0
            ) + int(row.cnt or 0)

    # Kontrakty wszystkich klientów z przypisaniami — JEDNO zapytanie zamiast
    # jednego na każdego DL (audyt N14). Contract.client_id daje wszystkich
    # kontraktorów klienta bez joina do zamówień.
    today = business_today()
    all_live_contracts = await load_current_contracts(
        db,
        (
            await db.execute(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
                .where(
                    Contract.client_id.in_(all_client_ids),
                    Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                )
            )
        ).scalars(),
        today,
    )

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

        # Tylko kontrakty OBECNE — ta sama reguła co profil i ranking (B46).
        dl_client_set = set(client_ids)
        margin_rows_dl = [c for c in all_live_contracts if c.client_id in dl_client_set]
        active_headcount = summarize_active_contracts(margin_rows_dl)
        # Kontrakt bez jednej nogi stawki (``unpriced``) nie zdejmuje kwoty
        # z wiersza DL — suma jest częściowa, jak kafel na profilu klienta;
        # kwotę kasuje wyłącznie brak kursu NBP (``incomplete``).
        (
            margin_lookup_dl,
            incomplete_margin_clients,
            unpriced_clients,
        ) = await _margin_lookup_pln(db, margin_rows_dl, today)
        margin_total = sum(margin_lookup_dl.values(), start=Decimal("0"))
        # Runda 8 (R8-N13-4): brak obecnych kontraktów to policzone 0 (jak
        # „Aktywne MRR" na profilu), a suma częściowa niesie liczbę klientów
        # z kontraktem bez wyceny — dotąd wyglądała na pełną.
        has_margin = not incomplete_margin_clients and (
            bool(margin_lookup_dl) or not margin_rows_dl
        )

        items.append(
            DlKpiRow(
                dl_user_id=dl_id,
                dl_name=slot["name"],
                dl_email=slot["email"],
                managed_clients_count=len(client_ids),
                head_clients_count=slot["head_count"],
                # Zero to liczba, nie brak — `or None` robiło z DL-a bez
                # zamówień „—", nie do odróżnienia od braku kursu.
                total_revenue=revenue_total if revenue_complete else None,
                active_revenue=active_revenue if revenue_complete else None,
                monthly_margin_total=margin_total if has_margin else None,
                monthly_margin_unpriced_clients=len(unpriced_clients),
                active_orders_count=active_orders_count,
                active_consultants=active_headcount.contractors,
                active_contracts=active_headcount.active_contracts,
            )
        )
    items.sort(key=lambda r: r.total_revenue or 0, reverse=True)
    return items
