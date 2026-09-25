"""Router `/api/my-clients` — Delivery client register + per-client dashboard.

Delivery Lead, Admin, Finance i Talent Community Manager widzą wszystkich
klientów. ``DeliveryLeadClientAssignment`` opisuje odpowiedzialność i flagę
głównego opiekuna, ale nie ogranicza dostępu operacyjnego.

Dashboard stosuje ten sam per-client guard, po rozwiązaniu merge redirectu.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from typing import Annotated, NamedTuple, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.responses import RedirectResponse

from app.api.clients import client_time_to_fill, polish_alphabetical_key
from app.api.deps import CurrentUser, require_delivery_lead_or_admin
from app.api.financial_access import can_read_client_finance, has_financial_access
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
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
from app.services.access_scope import (
    apply_delivery_lead_client_scope,
    assert_delivery_lead_client_visible,
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.client_identity import (
    client_display_name,
    client_display_name_expression,
    is_client_visible,
    resolve_visible_client,
    visible_client_predicates,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.contractor_identity import (
    load_current_contracts,
    summarize_active_contracts,
)
from app.services.fx_service import amount_to_pln_with_rate, rates_to_pln
from app.services.order_continuation import order_has_continuation
from app.services.order_revenue import (
    client_order_value_rows,
    order_counts_by_status,
    order_revenue_rows_to_pln,
)
from app.schemas.money import to_whole_pln
from app.core.scheduling import business_today

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


_MY_CLIENTS_ORGANIZATION_READ_ROLES = (
    UserRole.admin,
    UserRole.finance,
    UserRole.talent_community_manager,
)


# „Konsultant pracuje u tego klienta" = active LUB ending. Dzienny cron
# ``contract_alerts._promote_statuses`` przestawia active→ending na 30 dni
# przed końcem, a taki kontrakt nadal jest wykonywany i fakturowany. Liczenie
# samego ``active`` zdejmowało konsultanta z obu kafli naraz (nie przechodził
# do „zakończonych", tylko znikał) i ucinało jego marżę — podczas gdy profil
# tego samego klienta, o jedno kliknięcie dalej, liczył go dalej.
_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)

# Okno „kończy się wkrótce” (umowy ramowe na liście i alerty dashboardu).
EXPIRING_SOON_DAYS = 30


class MonthlyMarginTotals(NamedTuple):
    """Miesięczne agregaty jednego klienta, policzone z TYCH SAMYCH kontraktów.

    ``revenue`` jest tu po to, żeby procent marży miał mianownik w tej samej
    jednostce co licznik. Wcześniej dzieliliśmy marżę MIESIĘCZNĄ przez sumę
    ``ClientOrder.total_value`` — czyli przepływ na miesiąc przez wartość całych
    zamówień. Iloraz dwóch różnych wielkości nie znaczy nic: na produkcji dawał
    u Nordei 603,82%.
    """

    margin: Decimal
    revenue: Decimal
    has_margin: bool
    complete: bool
    # Obecne kontrakty bez stawki (którejś nogi) — pominięte w sumie. >0 =
    # kafel niepełny, jak „Aktywne MRR (niepełne)” na profilu (audyt S9).
    unpriced: int = 0


async def _monthly_margin_total_pln(
    db: AsyncSession,
    contracts: list[Contract],
    on: date,
) -> MonthlyMarginTotals:
    """Miesięczna marża i miesięczny przychód klienta w PLN.

    Obie nogi (przychodowa i kosztowa) są przewalutowane NIEZALEŻNIE. Gdy
    brakuje kursu, ``complete`` jest fałszywe, żeby wołający zwrócił ``None``
    zamiast podawać częściowy agregat jako pewny.

    ``revenue`` sumuje wyłącznie kontrakty, które weszły też do ``margin`` —
    kontrakt pominięty w liczniku (brak stawki, brak kursu) nie może zawyżać
    mianownika, bo procent przestałby opisywać ten sam zbiór.
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
    total = Decimal("0")
    revenue = Decimal("0")
    has_margin = False
    complete = True
    unpriced = 0
    for contract in contracts:
        fields = effective_rate_fields(contract, on)
        raw_client = fields["monthly_rate_client"]
        raw_candidate = fields["monthly_rate_candidate"]
        if raw_client is None or raw_candidate is None:
            unpriced += 1
            continue
        client_fx = fx_rates.get(contract.resolved_rate_client_currency)
        candidate_fx = fx_rates.get(contract.resolved_rate_candidate_currency)
        client_pln, client_complete = amount_to_pln_with_rate(raw_client, client_fx)
        candidate_pln, candidate_complete = amount_to_pln_with_rate(
            raw_candidate, candidate_fx
        )
        if not client_complete or not candidate_complete:
            complete = False
            continue
        assert client_pln is not None and candidate_pln is not None
        # Składniki zaokrąglane per kontrakt, jak wiersze tabeli konsultantów na
        # profilu — kafel Analityki musi równać się „Aktywnemu MRR” (UAT M06-B04).
        total += Decimal(to_whole_pln(client_pln - candidate_pln))
        revenue += Decimal(to_whole_pln(client_pln))
        has_margin = True
    return MonthlyMarginTotals(total, revenue, has_margin, complete, unpriced)


async def require_client_dashboard_access_after_merge(
    client_id: int,
    current_user: CurrentUser,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Authorize dashboard access against the canonical client identity."""
    canonical = await resolve_visible_client(db, client_id, follow_merge=True)
    if canonical is None:
        raise HTTPException(404, detail="Client not found")

    # Keep the Delivery Lead persona path for hybrids so its Delivery-specific
    # finance rules remain explicit. Operational access covers every canonical
    # client; financial fields are decided inside the handler.
    delivery_scoped = current_user.has_role(
        UserRole.delivery_lead
    ) and not current_user.has_any_role(UserRole.admin, UserRole.finance)
    if not delivery_scoped and current_user.has_any_role(
        *_MY_CLIENTS_ORGANIZATION_READ_ROLES
    ):
        return current_user

    await require_delivery_lead_or_admin(current_user=current_user)
    if delivery_scoped:
        # Portal DL pokazuje wyłącznie klientów z portfela (25.09.2026).
        assert_delivery_lead_client_visible(
            canonical.id, await resolve_delivery_lead_client_ids(current_user, db)
        )
    return current_user


CanonicalClientDashboardUser = Annotated[
    User,
    Depends(require_client_dashboard_access_after_merge),
]


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - business_today()).days


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
    """Client register for Delivery-facing personas.

    A Delivery Lead sees its portfolio (``resolve_delivery_lead_client_ids`` —
    assigned clients since 25.09.2026, every client under
    ``DL_CLIENT_SCOPE=all``); organization readers see every client.
    """
    # A concrete set identifies the Delivery Lead persona and keeps its
    # assigned-client finance exception separate from VIEW_FINANCE.
    delivery_lead_client_ids = await resolve_delivery_lead_client_ids(user, db)
    is_delivery_scoped = delivery_lead_client_ids is not None
    is_organization_reader = (
        user.has_any_role(*_MY_CLIENTS_ORGANIZATION_READ_ROLES)
        and not is_delivery_scoped
    )
    client_name = client_display_name_expression()

    if not is_delivery_scoped and not is_organization_reader:
        raise HTTPException(
            403,
            detail="Only Delivery Leads or organization readers can view clients",
        )

    clients_stmt = apply_delivery_lead_client_scope(
        select(Client)
        .where(*visible_client_predicates())
        .order_by(polish_alphabetical_key(client_name).asc(), Client.id.asc()),
        Client.id,
        delivery_lead_client_ids,
    )
    clients = list((await db.execute(clients_stmt)).scalars())
    client_ids = [client.id for client in clients]

    # Assignment also answers "is this person the head DL?" and which client
    # finance they own.
    head_lookup: dict[int, bool] = {}
    assigned_client_ids: frozenset[int] = frozenset()
    if is_delivery_scoped:
        assigned_client_ids = (
            await resolve_delivery_lead_finance_client_ids(user, db) or frozenset()
        )
        if assigned_client_ids:
            assignments = list(
                (
                    await db.execute(
                        select(
                            DeliveryLeadClientAssignment.client_id,
                            DeliveryLeadClientAssignment.is_head,
                        ).where(
                            DeliveryLeadClientAssignment.delivery_lead_user_id
                            == user.id,
                            DeliveryLeadClientAssignment.client_id.in_(
                                sorted(assigned_client_ids)
                            ),
                        )
                    )
                )
            )
            head_lookup = {
                assignment.client_id: assignment.is_head for assignment in assignments
            }

    if not client_ids:
        return []

    finance_client_ids = (
        frozenset(client_ids) if has_financial_access(user) else assigned_client_ids
    )

    # Aktywne zamówienia — licznik jest operacyjny dla każdego dopuszczonego
    # czytelnika Delivery, w tym TCM. Zamówienie MD/kosztowe to jedno
    # zamówienie, nie liczba osób na nim (audyt W1).
    active_order_counts = {
        cid: counts.get(ClientOrderStatus.active.value, 0)
        for cid, counts in order_counts_by_status(
            await client_order_value_rows(db, client_ids, with_values=False)
        ).items()
    }

    # Kwot nie pobieramy nawet z bazy dla ról bez VIEW_FINANCE. Dzięki temu
    # ukrycie kart na froncie nie jest jedyną granicą bezpieczeństwa.
    active_revenue: dict[int, Decimal] = {}
    lifetime_revenue: dict[int, Decimal] = {}
    if finance_client_ids:
        revenue_rows = await client_order_value_rows(db, finance_client_ids)
        revenue_lookup, revenue_incomplete = await order_revenue_rows_to_pln(
            db, revenue_rows, business_today()
        )
        # Klient z uprawnieniami, ale bez żadnego zamówienia, dostaje 0 —
        # tak samo jak w `/dashboard`. Pominięty klucz czyta się jak redakcja.
        for client_id in finance_client_ids:
            if client_id in revenue_incomplete:
                continue
            totals = revenue_lookup.get(client_id)
            active_revenue[client_id] = totals["active"] if totals else Decimal(0)
            lifetime_revenue[client_id] = totals["total"] if totals else Decimal(0)

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
    today = business_today()
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
                    # Okno [dziś, dziś + 30 dni] — to samo co alerty
                    # dashboardu. Do 24.09.2026 warunek był `<= dziś`, więc
                    # liczył umowy JUŻ wygasłe, a te kończące się pomijał.
                    ClientFrameworkContract.expiry_date >= today,
                    ClientFrameworkContract.expiry_date
                    <= today + timedelta(days=EXPIRING_SOON_DAYS),
                )
                .group_by(ClientFrameworkContract.client_id)
            )
        )
    }

    items: list[MyClientRow] = []
    for c in clients:
        fc = fc_lookup.get(c.id)
        items.append(
            MyClientRow(
                client_id=c.id,
                name=client_display_name(c),
                industry=getattr(c, "industry", None),
                is_head_dl=head_lookup.get(c.id, False),
                active_orders_count=active_order_counts.get(c.id, 0),
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
    user: CanonicalClientDashboardUser,
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

    # Ta sama reguła co na profilu klienta: role z ``VIEW_FINANCE`` oraz
    # Delivery Lead w finansowej granicy własnego portfela. Dostęp operacyjny
    # do dashboardu jest już globalny, ale kwoty pozostają węższe.
    finance_ok = can_read_client_finance(
        user,
        client_id=client_id,
        delivery_lead_finance_client_ids=(
            await resolve_delivery_lead_finance_client_ids(user, db)
        ),
    )

    # Liczba i wartość zamówień: samodzielne + zamówienia MD/kosztowe jako
    # JEDNO zamówienie, bez szkiców (``client_order_value_rows``, audyt W1).
    # Liczniki są operacyjne; kwoty czytamy z bazy wyłącznie przy prawie do
    # finansów tego klienta.
    revenue_rows = await client_order_value_rows(
        db, [client_id], with_values=finance_ok
    )
    order_status_counts = order_counts_by_status(revenue_rows).get(client_id, {})

    # Revenue: lifetime total / active / completed. The query itself is
    # finance-gated; TCM never loads raw amounts, while an assigned DL uses the
    # narrow per-client finance exception established above.
    total_rev = Decimal(0)
    active_rev = Decimal(0)
    completed_rev = Decimal(0)
    revenue_fx_complete = True
    currency_breakdown: dict[str, Decimal] = {}
    if finance_ok:
        finance_on = business_today()
        revenue_lookup, revenue_incomplete = await order_revenue_rows_to_pln(
            db, revenue_rows, finance_on
        )
        revenue_totals = revenue_lookup.get(
            client_id,
            {
                "total": Decimal("0"),
                "active": Decimal("0"),
                "completed": Decimal("0"),
            },
        )
        revenue_fx_complete = client_id not in revenue_incomplete
        if revenue_fx_complete:
            total_rev = revenue_totals["total"]
            active_rev = revenue_totals["active"]
            completed_rev = revenue_totals["completed"]
        for row in revenue_rows:
            value = Decimal(row.sum_val) if row.sum_val is not None else Decimal(0)
            if row.status == ClientOrderStatus.cancelled:
                continue
            if row.currency:
                currency_breakdown[row.currency] = (
                    currency_breakdown.get(row.currency, Decimal(0)) + value
                )

    # Same split for contracts: status counts are operational, while margin
    # calculation loads full financial rows only for VIEW_FINANCE.
    count_contracts = list(
        (
            await db.execute(
                select(Contract)
                .where(Contract.client_id == client_id)
                .options(selectinload(Contract.candidate))
            )
        )
        .scalars()
        .all()
    )
    monthly_margin_total: Decimal | int = 0
    monthly_revenue_total: Decimal = Decimal("0")
    has_margin = False
    margin_complete = True
    margin_unpriced = 0
    # „Dziś” poza gałęzią finansową: czyta je też liczenie aktywnych
    # konsultantów niżej, a odbiorca bez kwot dostawał tu 500 (NameError).
    today = business_today()
    if finance_ok:
        # Filtr statusu zszedł do WHERE (wcześniej ładowaliśmy WSZYSTKIE
        # kontrakty klienta — szkice, zakończone, anulowane — żeby odsiać je
        # w Pythonie), a stawki idą z harmonogramów: kolumna ``rate_*`` niesie
        # wartość z ostatniego ZAPISU kontraktu, więc krok progresywny albo
        # aneks z datą, która już nadeszła, dawały tu starą marżę.
        contract_rows = list(
            (
                await db.execute(
                    select(Contract)
                    .options(*RATE_SCHEDULE_LOADS)
                    .where(
                        Contract.client_id == client_id,
                        Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                    )
                )
            ).scalars()
        )
        # Tylko kontrakty OBECNE — ta sama reguła co kafel „Aktywne MRR"
        # na profilu tego klienta (UAT B46). Pusta data startu znaczy „start
        # nieznany", nie „planowany" (audyt 18.09.2026).
        contract_rows = await load_current_contracts(db, contract_rows, today)
        totals = await _monthly_margin_total_pln(db, contract_rows, today)
        monthly_margin_total = totals.margin
        monthly_revenue_total = totals.revenue
        has_margin = totals.has_margin
        margin_complete = totals.complete
        margin_unpriced = totals.unpriced

    # Marża % = marża MIESIĘCZNA / przychód MIESIĘCZNY, obie nogi z tego samego
    # zbioru kontraktów. Mianownikiem NIE jest suma `ClientOrder.total_value`:
    # to wartość całych zamówień, a nie przepływ na miesiąc. Dzielenie
    # przepływu przez wartość całkowitą dawało liczbę bez znaczenia — na
    # produkcji 603,82% u Nordei (1 833 307 zł/mc marży przez 303 616 zł
    # wartości zamówień).
    #
    # `revenue_fx_complete` NIE jest już warunkiem: dotyczy przewalutowania
    # zamówień, których ten wskaźnik przestał używać. Kompletność kursów dla
    # stawek kontraktowych niesie `margin_complete`.
    margin_pct: Optional[float] = None
    if margin_complete and has_margin and monthly_revenue_total > 0:
        margin_pct = round(
            float(monthly_margin_total) / float(monthly_revenue_total) * 100, 2
        )

    # Konsultanci active vs completed (na podstawie kontraktów linkowanych do orderów)
    live_contracts = [
        contract
        for contract in count_contracts
        if contract.status in _LIVE_CONTRACT_STATUSES
    ]
    active_headcount = summarize_active_contracts(
        await load_current_contracts(db, live_contracts, today)
    )
    completed_consultants = sum(
        1 for contract in count_contracts if contract.status == ContractStatus.ended
    )

    # Średni czas obsadzenia — TA SAMA definicja co profil klienta (start
    # kontraktu − otwarcie rekrutacji). Do 24.09.2026 liczyło się tu
    # `start − created_at` zakończonych zamówień, czyli odległość wpisania
    # zamówienia do systemu od jego startu, pod etykietą „czas obsadzenia” (S9).
    avg_ttf, _ttf_not_assessable = await client_time_to_fill(db, client_id)
    avg_days_to_fill = round(avg_ttf, 1) if avg_ttf is not None else None

    # Counts
    fc_count = (
        await db.scalar(
            select(func.count())
            .select_from(ClientFrameworkContract)
            .where(ClientFrameworkContract.client_id == client_id)
        )
    ) or 0
    active_orders_count = order_status_counts.get(ClientOrderStatus.active.value, 0)
    completed_orders_count = order_status_counts.get(
        ClientOrderStatus.completed.value, 0
    )

    # Alerts: framework contracts expiring 30/14/7 dni + ordery ending 30/14/7 dni
    today = business_today()
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
                    # Zamówienie z dodaną kontynuacją nie wymaga działania —
                    # ta sama reguła co zakładka „Kończące się 30d” i karta
                    # w panelu „Moi klienci” (audyt S9).
                    ~order_has_continuation(),
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
        # Zero z uprawnieniami to liczba, nie brak: `or None` zamieniało
        # klienta bez zamówień w pominięty klucz, który ekran pokazuje jako
        # „—", czyli tak samo jak redakcję — a lista `/api/my-clients` dla
        # tego samego klienta zwracała „0".
        total_revenue_all_time=(
            total_rev if finance_ok and revenue_fx_complete else None
        ),
        active_revenue=(active_rev if finance_ok and revenue_fx_complete else None),
        completed_revenue=(
            completed_rev if finance_ok and revenue_fx_complete else None
        ),
        currency_breakdown=currency_breakdown if finance_ok else None,
        monthly_margin_total=(
            monthly_margin_total
            if finance_ok and has_margin and margin_complete
            else None
        ),
        monthly_margin_pct=margin_pct if finance_ok else None,
        monthly_margin_unpriced_contracts=margin_unpriced if finance_ok else None,
        active_consultants=active_headcount.contractors,
        active_contracts=active_headcount.active_contracts,
        completed_consultants=completed_consultants,
        avg_days_to_fill=avg_days_to_fill,
        framework_contracts_count=fc_count,
        active_orders_count=active_orders_count,
        completed_orders_count=completed_orders_count,
        alerts=alerts,
    )
