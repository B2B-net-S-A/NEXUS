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
from app.models.client import Client
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractStatus,
)
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.team_structure import DeliveryLeadClientAssignment
from app.models.user import User
from app.schemas.admin_clients_overview import DlKpiRow, OverviewRow
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.contractor_identity import (
    count_unique_contractors,
    summarize_active_contracts,
)
from app.services.fx_service import amount_to_pln_with_rate, rates_to_pln
from app.services.order_revenue import order_revenue_rows_to_pln

router = APIRouter()


# „Konsultant pracuje u tego klienta" = active LUB ending. Dzienny cron
# ``contract_alerts._promote_statuses`` przestawia active→ending 30 dni przed
# końcem, a konsultant w ostatnim miesiącu wciąż pracuje i wciąż fakturuje —
# liczenie samego ``active`` zdejmowało go z liczby głów i wycinało całą jego
# marżę, przez co ten ekran przeczył profilowi klienta (``clients.py``) i
# banerowi wygasających (``contracts.py``), które od dawna liczą oba statusy.
# Marża idzie z HARMONOGRAMÓW, nie z kolumn ``contracts.rate_*``: kolumna
# niesie kwotę z ostatniego ZAPISU kontraktu, więc krok progresywny albo aneks
# z datą, która już nadeszła, pokazywały tu marżę pierwszego okresu.
_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)


async def _margin_lookup_pln(
    db: AsyncSession,
    contracts: list[Contract],
    on: date,
) -> tuple[dict[int, Decimal], set[int]]:
    """Aggregate per-client margin after converting both rate legs to PLN.

    The returned set contains clients for which at least one priced contract
    needs an unavailable FX rate. Callers keep their margin ``None`` rather
    than silently exposing a partial sum.
    """

    currencies = {
        currency
        for contract in contracts
        for currency in (
            contract.resolved_rate_client_currency,
            contract.resolved_rate_candidate_currency,
        )
    }
    fx_rates = await rates_to_pln(db, currencies, on)
    totals: dict[int, Decimal] = {}
    incomplete: set[int] = set()
    for contract in contracts:
        fields = effective_rate_fields(contract, on)
        raw_client = fields["monthly_rate_client"]
        raw_candidate = fields["monthly_rate_candidate"]
        if raw_client is None or raw_candidate is None:
            continue
        client_fx = fx_rates.get(contract.resolved_rate_client_currency)
        candidate_fx = fx_rates.get(contract.resolved_rate_candidate_currency)
        client_pln, client_complete = amount_to_pln_with_rate(raw_client, client_fx)
        candidate_pln, candidate_complete = amount_to_pln_with_rate(
            raw_candidate, candidate_fx
        )
        if not client_complete or not candidate_complete:
            incomplete.add(contract.client_id)
            continue
        assert client_pln is not None and candidate_pln is not None
        margin_pln = client_pln - candidate_pln
        totals[contract.client_id] = (
            totals.get(contract.client_id, Decimal("0")) + margin_pln
        )
    for client_id in incomplete:
        totals.pop(client_id, None)
    return totals, incomplete


@router.get("", response_model=list[OverviewRow])
async def clients_overview(
    _user: FinanceReadUser,
    db: AsyncSession = Depends(get_db),
):
    # Nazwa prezentowana + tylko widoczne wiersze — ta sama para reguł co
    # `my_clients.py` / `search.py` (`services/client_identity.py`). Surowe
    # `Client.name` pokazywałoby nazwę sprzed ręcznej poprawki (na prodzie 24/160
    # klientów), a brak filtra dorzucał 12 scalonych duplikatów jako wiersze
    # z zerami. Sortowanie po `lower(effective_name)` jest tie-breakiem widocznej
    # kolejności: końcowy `items.sort` po revenue jest STABILNY, a większość
    # klientów ma revenue NULL, więc to ono decyduje o kolejności na ekranie.
    effective_name = client_display_name_expression()
    client_rows = list(
        (
            await db.execute(
                select(Client, effective_name.label("effective_name"))
                .where(*visible_client_predicates())
                .order_by(func.lower(effective_name).asc(), Client.id.asc())
            )
        ).all()
    )

    rev_rows = list(
        (
            await db.execute(
                select(
                    ClientOrder.client_id,
                    ClientOrder.status,
                    ClientOrder.currency,
                    func.coalesce(func.sum(ClientOrder.total_value), 0).label(
                        "sum_val"
                    ),
                    func.count().label("cnt"),
                )
                .where(ClientOrder.status != ClientOrderStatus.cancelled)
                .group_by(
                    ClientOrder.client_id,
                    ClientOrder.status,
                    ClientOrder.currency,
                )
            )
        )
    )
    rev_lookup, rev_incomplete = await order_revenue_rows_to_pln(
        db, rev_rows, date.today()
    )
    active_order_counts: dict[int, int] = {}
    for r in rev_rows:
        if r.status == ClientOrderStatus.active:
            active_order_counts[r.client_id] = active_order_counts.get(
                r.client_id, 0
            ) + int(r.cnt or 0)

    # Head DL = klient ma assignment z is_head=True. Jeśli admin nie
    # zaznaczył nikogo jako Head (data quality issue — większość klientów
    # nie ma jeszcze przypisanego), fallback do dowolnego DL przypisanego
    # do klienta. Bez fallbacku kolumna "Head DL" pokazuje "brak" dla
    # 156/158 klientów (QA 2026-05-27, NEXUS-FE Insights).
    head_dl_rows = list(
        (
            await db.execute(
                select(
                    DeliveryLeadClientAssignment.client_id,
                    DeliveryLeadClientAssignment.is_head,
                    User.id,
                    User.name,
                )
                .join(
                    User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id
                )
                # Preferuj is_head=true (sortowanie po nim DESC), tie-break
                # po user.id DESC (nowsze konto @inframinds.eu).
                .order_by(
                    DeliveryLeadClientAssignment.is_head.desc(),
                    User.id.desc(),
                )
            )
        )
    )
    head_dl_lookup: dict[int, tuple[int, str]] = {}
    for r in head_dl_rows:
        # Pierwszy wpis per client_id wygrywa (order_by gwarantuje że to
        # is_head=True jeśli istnieje, inaczej dowolny DL).
        if r.client_id not in head_dl_lookup:
            head_dl_lookup[r.client_id] = (r.id, r.name)

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

    # Refactor 2026-05-11: Contract.client_id daje wszystkich kontraktorów u klienta
    # (1 Contract = 1 kontraktor, brak M:N).
    margin_rows = list(
        (
            await db.execute(
                select(Contract)
                .options(*RATE_SCHEDULE_LOADS, selectinload(Contract.candidate))
                .where(Contract.status.in_(_LIVE_CONTRACT_STATUSES))
            )
        ).scalars()
    )
    contractor_candidates: dict[int, list] = {}
    active_contracts_lookup: dict[int, int] = {}
    today = date.today()
    for r in margin_rows:
        active_contracts_lookup[r.client_id] = (
            active_contracts_lookup.get(r.client_id, 0) + 1
        )
        if r.candidate is not None:
            contractor_candidates.setdefault(r.client_id, []).append(r.candidate)
    margin_lookup, _ = await _margin_lookup_pln(db, margin_rows, today)

    items: list[OverviewRow] = []
    for c, effective in client_rows:
        rev = rev_lookup.get(c.id, {"total": None, "active": None})
        revenue_complete = c.id not in rev_incomplete
        head = head_dl_lookup.get(c.id)
        fc = fc_lookup.get(c.id)
        items.append(
            OverviewRow(
                client_id=c.id,
                name=effective,
                industry=getattr(c, "industry", None),
                head_dl_id=head[0] if head else None,
                head_dl_name=head[1] if head else None,
                total_revenue_all_time=(rev["total"] or None)
                if revenue_complete
                else None,
                active_revenue=(rev["active"] or None) if revenue_complete else None,
                monthly_margin_total=margin_lookup.get(c.id),
                active_orders_count=active_order_counts.get(c.id, 0),
                active_consultants=count_unique_contractors(
                    contractor_candidates.get(c.id, [])
                ),
                active_contracts=active_contracts_lookup.get(c.id, 0),
                framework_status=fc[0] if fc else None,
                framework_expiry_date=fc[1] if fc else None,
            )
        )

    items.sort(
        key=lambda r: r.total_revenue_all_time or 0,
        reverse=True,
    )
    return items


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
