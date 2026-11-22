"""Client portfolio directory and manually managed portfolio scopes.

The directory is deliberately scope-shaped: one client may appear in more than
one row when it has more than one commercial scope.  Tile counters, however,
count distinct clients so a multi-scope client does not inflate the headline
number.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from io import BytesIO
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, case, distinct, exists, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import aliased, selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.candidate_access import NOT_READ_ONLY
from app.api.clients import polish_alphabetical_key
from app.api.deps import AdminUser, OperationalUser
from app.api.financial_access import list_finance_client_ids
from app.api.my_clients import _monthly_margin_total_pln
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.export_safety import safe_cell
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_directory import (
    ClientAlias,
    ClientPortfolioScope,
    PortfolioCategory,
)
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus
from app.models.job import Job, JobStatus
from app.models.user import User
from app.schemas.client_directory import (
    ClientDirectoryCategoryCounts,
    ClientDirectoryItem,
    ClientDirectoryResponse,
    ClientListConsultantAttention,
    ClientListDeliveryLead,
    ClientListItem,
    ClientListResponse,
    ClientListStateCounts,
    ClientPortfolioScopeCreate,
    ClientPortfolioScopePlacementUpdate,
    ClientPortfolioScopeResponse,
    ClientPortfolioScopeUpdate,
)
from app.models.team_structure import ClientTacAssignment, DeliveryLeadClientAssignment
from app.services.access_scope import (
    resolve_delivery_lead_client_ids,
    resolve_delivery_lead_finance_client_ids,
)
from app.services.action_permissions import ProductAction, has_permission
from app.services.client_identity import (
    client_display_name_expression,
    visible_client_predicates,
)
from app.services.consultant_order_state import (
    ATTENTION_NO_CURRENT_ORDER,
    ATTENTION_NOTICE,
    ATTENTION_ORDER_ENDING,
    consultant_order_state,
)
from app.services.contract_rates import RATE_SCHEDULE_LOADS
from app.services.contractor_identity import (
    contractor_identity_sql_expression,
    current_contract_clause,
    load_current_contracts,
)
from app.services.polish_ilike import polish_folded_ilike
from app.core.scheduling import business_today

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


def _can_view_directory_legal(user: User) -> bool:
    """Dane prawne klienta (nazwa prawna, NIP, REGON) w katalogu.

    Idą razem z dokumentami, które mogą nieść stawki — uprawnienie „Stawki
    i kwoty: podgląd” (domyślnie admin, Finanse, Delivery Lead). Konto z samym
    podglądem Delivery (np. Talent Community Manager) dostaje katalog bez nich.
    """

    return has_permission(user, ProductAction.amounts_view)


def _effective_client_name():
    """SQL expression for the NEXUS-owned canonical display name.

    Cienki alias na `client_identity.client_display_name_expression` — reguła ma
    jedną definicję (ten plik i `api/clients.py` trzymały jej dosłowne kopie).
    """

    return client_display_name_expression()


def _visible_client_filters() -> tuple:
    """Cienki alias na `client_identity.visible_client_predicates` (była kopia)."""

    return visible_client_predicates()


def _contract_scope_bucket():
    """Zakres portfela, do którego kontrakt przypięto przez umowę ramową.

    Kontrakt należy do zakresu, którego umowę ramową (MSA) wskazuje którekolwiek
    jego nieanulowane zamówienie u tego samego klienta; kilka — najniższy
    ``scope.id``. ``NULL`` = kontrakt nieprzypięty do żadnego zakresu.
    """

    return (
        select(func.min(ClientPortfolioScope.id))
        .select_from(ClientOrder)
        .join(
            ClientPortfolioScope,
            and_(
                ClientPortfolioScope.framework_contract_id
                == ClientOrder.framework_contract_id,
                ClientPortfolioScope.client_id == Contract.client_id,
                ClientPortfolioScope.archived_at.is_(None),
            ),
        )
        .where(
            ClientOrder.contract_id == Contract.id,
            ClientOrder.client_id == Contract.client_id,
            ClientOrder.framework_contract_id.is_not(None),
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
        .correlate(Contract)
        .scalar_subquery()
    )


def _scope_has_own_contracts():
    """Czy do zakresu przypięto choć jeden kontrakt (przez MSA zamówienia).

    Taki zakres liczy WYŁĄCZNIE swoje kontrakty. Liczone ze wszystkich
    nieanulowanych zamówień, nie tylko bieżących kontraktów — zakres, którego
    jedyny konsultant odszedł, ma pokazać 0, a nie wrócić do liczby całego
    klienta (zgłoszenie 28.09.2026: „Nordea Bank Abp – Pentesty” pokazywało
    292 konsultantów Nordei zamiast jednego swojego).
    """

    return exists(
        select(ClientOrder.id).where(
            ClientOrder.framework_contract_id
            == ClientPortfolioScope.framework_contract_id,
            ClientOrder.client_id == ClientPortfolioScope.client_id,
            ClientOrder.status != ClientOrderStatus.cancelled,
        )
    ).correlate(ClientPortfolioScope)


def _client_has_pin_free_scope():
    """Czy klient ma inny żywy zakres bez przypiętych kontraktów.

    Bez takiego zakresu kontrakty nieprzypięte liczy zakres z przypięciami —
    inaczej wypadłyby z katalogu (np. przypięcie jednego kontraktu do umowy
    ramowej jedynego zakresu klienta zdjęłoby z licznika całą resztę).
    """

    other = aliased(ClientPortfolioScope)
    return exists(
        select(other.id).where(
            other.client_id == ClientPortfolioScope.client_id,
            other.id != ClientPortfolioScope.id,
            other.archived_at.is_(None),
            ~exists(
                select(ClientOrder.id).where(
                    ClientOrder.framework_contract_id == other.framework_contract_id,
                    ClientOrder.client_id == other.client_id,
                    ClientOrder.status != ClientOrderStatus.cancelled,
                )
            ),
        )
    ).correlate(ClientPortfolioScope)


def _active_consultants_subquery(as_of: date, *, by_scope: bool = True):
    """Date-effective consultant count per (client, scope bucket), by person.

    ``scope_id`` is the scope a contract is pinned to (``_contract_scope_bucket``)
    or ``NULL`` for contracts pinned to no scope.  A client without pinned
    contracts has a single ``NULL`` bucket, so every scope row still shows the
    whole client — the behaviour before 28.09.2026.

    ``by_scope=False`` liczy całego klienta (lista „Klienci”, jeden wiersz na
    klienta) — ta sama reguła „obecnego” kontraktu, bez podziału na zakresy.
    """

    identity_key = contractor_identity_sql_expression(
        Candidate.name,
        Candidate.lastname,
        Candidate.email,
        Candidate.id,
    )

    scope_column = [_contract_scope_bucket().label("scope_id")] if by_scope else []
    current = (
        select(
            Contract.id.label("contract_id"),
            Contract.client_id.label("client_id"),
            *scope_column,
            identity_key.label("identity_key"),
            Candidate.id.label("candidate_id"),
        )
        # A deleted candidate is detached from its contracts.  Such a row is
        # still an active contract and must remain in ``active_contracts``;
        # the aggregate FILTER keeps it out of the people headcount.
        .outerjoin(Candidate, Contract.candidate_id == Candidate.id)
        .where(
            Contract.status.in_((ContractStatus.active, ContractStatus.ending)),
            # Pusta data startu = start NIEZNANY, nie „planowany na przyszłość”
            # — lustro `contractor_identity.is_current_contract` (audyt
            # 18.09.2026: trzy aktywne kontrakty z żywymi zamówieniami znikały
            # z liczników i z MRR, bo nikt nie wpisał dnia rozpoczęcia).
            # Kontrakt bez daty startu pyta o nią swoje zamówienia — lustro
            # `fallback_start` z profilu (`load_fallback_starts`): planowany
            # jest wyłącznie wtedy, gdy ma nieanulowane zamówienia i żadne
            # z nich jeszcze się nie zaczęło (audyt 24.09.2026, S5). Bez
            # filtra po `end_date` — profil też go nie ma, o końcu decyduje
            # status umowy (N11).
            current_contract_clause(as_of),
        )
        .subquery()
    )

    group_columns = (
        [current.c.client_id, current.c.scope_id] if by_scope else [current.c.client_id]
    )
    return (
        select(
            *group_columns,
            func.count(distinct(current.c.identity_key))
            .filter(current.c.candidate_id.is_not(None))
            .label("active_consultants"),
            func.count(current.c.contract_id).label("active_contracts"),
        )
        .group_by(*group_columns)
        .subquery()
    )


def _directory_rows_statement(
    *,
    category: PortfolioCategory,
    q: Optional[str],
    as_of: date,
    allowed_client_ids: frozenset[int] | None = None,
):
    canonical_name = _effective_client_name()
    scope_label = func.nullif(func.btrim(ClientPortfolioScope.label), "")
    active_consultants = _active_consultants_subquery(as_of)
    own_contracts = _scope_has_own_contracts()

    # Effective placement: a manual override wins over the manifest ``category``
    # and the linked-MSA dates.  The manifest consistency invariant keeps
    # reading the raw base columns, so this display-time preference never trips
    # ``applied_manifest_state_inconsistent``.
    effective_category = func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )
    effective_start = func.coalesce(
        ClientPortfolioScope.contract_start_override,
        ClientFrameworkContract.effective_date,
    )
    effective_end = func.coalesce(
        ClientPortfolioScope.contract_end_override,
        ClientFrameworkContract.expiry_date,
    )
    # A row carries a contract period if it links an MSA or pins either date.
    has_contract_period = or_(
        ClientPortfolioScope.framework_contract_id.is_not(None),
        ClientPortfolioScope.contract_start_override.is_not(None),
        ClientPortfolioScope.contract_end_override.is_not(None),
    )

    statement = (
        select(
            ClientPortfolioScope.id.label("scope_id"),
            Client.id.label("client_id"),
            canonical_name.label("display_name"),
            Client.legal_name.label("legal_name"),
            Client.nip.label("nip"),
            Client.regon.label("regon"),
            Client.industry.label("industry"),
            effective_category.label("category"),
            ClientPortfolioScope.category.label("category_base"),
            ClientPortfolioScope.category_override.label("category_override"),
            ClientPortfolioScope.contract_start_override.label(
                "contract_start_override"
            ),
            ClientPortfolioScope.contract_end_override.label("contract_end_override"),
            scope_label.label("scope_label"),
            ClientPortfolioScope.framework_contract_id.label("msa_id"),
            effective_start.label("effective_date"),
            effective_end.label("expiry_date"),
            has_contract_period.label("has_contract_period"),
            Client.status.label("client_status"),
            func.coalesce(active_consultants.c.active_consultants, 0).label(
                "active_consultants_count"
            ),
            func.coalesce(active_consultants.c.active_contracts, 0).label(
                "active_contracts_count"
            ),
            and_(own_contracts, _client_has_pin_free_scope()).label(
                "counts_own_contracts"
            ),
        )
        .select_from(ClientPortfolioScope)
        .join(Client, Client.id == ClientPortfolioScope.client_id)
        .outerjoin(
            ClientFrameworkContract,
            and_(
                ClientFrameworkContract.id
                == ClientPortfolioScope.framework_contract_id,
                ClientFrameworkContract.client_id == Client.id,
            ),
        )
        .outerjoin(
            active_consultants,
            and_(
                active_consultants.c.client_id == Client.id,
                # Zakres z przypiętymi kontraktami liczy tylko swoje; pozostałe
                # zakresy klienta — kontrakty nieprzypięte do żadnego zakresu.
                or_(
                    and_(
                        own_contracts,
                        active_consultants.c.scope_id == ClientPortfolioScope.id,
                    ),
                    and_(
                        active_consultants.c.scope_id.is_(None),
                        or_(~own_contracts, ~_client_has_pin_free_scope()),
                    ),
                ),
            ),
        )
        .where(
            ClientPortfolioScope.archived_at.is_(None),
            effective_category == category,
            *_visible_client_filters(),
        )
    )
    if allowed_client_ids is not None:
        statement = statement.where(Client.id.in_(sorted(allowed_client_ids) or [-1]))

    normalized_q = (q or "").strip()
    if normalized_q:
        # Bez wrażliwości na polskie znaki: „spolka" znajduje „Spółka" (UAT M06-B03).
        statement = statement.where(
            or_(
                polish_folded_ilike(canonical_name, normalized_q),
                polish_folded_ilike(Client.legal_name, normalized_q),
                polish_folded_ilike(Client.name, normalized_q),
                polish_folded_ilike(Client.industry, normalized_q),
                polish_folded_ilike(ClientPortfolioScope.label, normalized_q),
                exists(
                    select(ClientAlias.id).where(
                        ClientAlias.client_id == Client.id,
                        ClientAlias.archived_at.is_(None),
                        polish_folded_ilike(ClientAlias.alias, normalized_q),
                    )
                ),
            )
        )

    # Polski alfabet („Ł” po „L”, nie za „Z”) — ta sama funkcja co
    # `GET /api/clients` (audyt N11).
    return statement.order_by(
        polish_alphabetical_key(canonical_name).asc(),
        polish_alphabetical_key(func.coalesce(scope_label, "")).asc(),
        ClientPortfolioScope.id.asc(),
    )


def _directory_counts_statement(
    *,
    allowed_client_ids: frozenset[int] | None = None,
):
    # Group by the EFFECTIVE category so a manually-moved client is counted in
    # the tab it actually appears in (mirrors the row query's COALESCE).
    effective_category = func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )
    statement = (
        select(
            effective_category.label("category"),
            func.count(distinct(ClientPortfolioScope.client_id)),
        )
        .select_from(ClientPortfolioScope)
        .join(Client, Client.id == ClientPortfolioScope.client_id)
        .where(
            ClientPortfolioScope.archived_at.is_(None),
            *_visible_client_filters(),
        )
        .group_by(effective_category)
    )
    if allowed_client_ids is not None:
        statement = statement.where(Client.id.in_(sorted(allowed_client_ids) or [-1]))
    return statement


async def _own_client_ids(user: User, db: AsyncSession) -> frozenset[int]:
    """Klienci, za których osoba odpowiada: przypisanie DL albo TAC.

    Zasila przełącznik „Moi / Wszyscy" w katalogu (dawny „Panel klientów").
    To FILTR widoku, nie granica dostępu — zakres danych nadal wyznacza
    ``resolve_delivery_lead_client_ids``.
    """

    dl_ids = await db.scalars(
        select(DeliveryLeadClientAssignment.client_id).where(
            DeliveryLeadClientAssignment.delivery_lead_user_id == user.id
        )
    )
    tac_ids = await db.scalars(
        select(ClientTacAssignment.client_id).where(
            ClientTacAssignment.tac_user_id == user.id
        )
    )
    return frozenset(int(i) for i in [*dl_ids.all(), *tac_ids.all()])


async def _directory_client_scope(
    user: User, db: AsyncSession, *, mine: bool
) -> frozenset[int] | None:
    allowed = await resolve_delivery_lead_client_ids(user, db)
    if not mine:
        return allowed
    own = await _own_client_ids(user, db)
    return own if allowed is None else own & allowed


@router.get("/directory", response_model=ClientDirectoryResponse)
async def list_client_directory(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    category: PortfolioCategory = Query(PortfolioCategory.active),
    q: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    mine: bool = Query(False),
):
    """Return one row per portfolio scope for the selected category.

    ``mine=true`` zawęża listę (i liczniki zakładek) do klientów, do których
    osoba jest przypisana jako Delivery Lead albo TAC.

    Search is intentionally limited to the selected category.  Tile counts are
    not affected by search and represent unique visible clients in every
    category.
    """

    as_of = business_today()
    allowed_client_ids = await _directory_client_scope(current_user, db, mine=mine)
    rows_statement = _directory_rows_statement(
        category=category,
        q=q,
        as_of=as_of,
        allowed_client_ids=allowed_client_ids,
    )
    filtered_rows = rows_statement.order_by(None).subquery()
    total_rows = int(
        (await db.execute(select(func.count()).select_from(filtered_rows))).scalar_one()
    )
    total_clients = int(
        (
            await db.execute(
                select(func.count(distinct(filtered_rows.c.client_id))).select_from(
                    filtered_rows
                )
            )
        ).scalar_one()
    )

    result = await db.execute(
        rows_statement.offset((page - 1) * page_size).limit(page_size)
    )
    can_view_legal = _can_view_directory_legal(current_user)
    items = [
        ClientDirectoryItem(
            scope_id=row.scope_id,
            client_id=row.client_id,
            msa_id=row.msa_id,
            display_name=row.display_name,
            legal_name=row.legal_name if can_view_legal else None,
            scope_label=row.scope_label,
            industry=row.industry,
            active_consultants_count=int(row.active_consultants_count or 0),
            active_contracts_count=int(row.active_contracts_count or 0),
            consultants_scope="scope" if row.counts_own_contracts else "client",
            effective_date=row.effective_date,
            expiry_date=row.expiry_date,
            category=row.category,
            category_base=row.category_base,
            client_status=row.client_status,
            category_override=row.category_override,
            contract_start_override=row.contract_start_override,
            contract_end_override=row.contract_end_override,
        )
        for row in result.all()
    ]

    raw_counts = (
        await db.execute(
            _directory_counts_statement(allowed_client_ids=allowed_client_ids)
        )
    ).all()
    category_counts = ClientDirectoryCategoryCounts(
        **{
            (
                category_value.value
                if hasattr(category_value, "value")
                else category_value
            ): int(count)
            for category_value, count in raw_counts
        }
    )

    return ClientDirectoryResponse(
        items=items,
        total_rows=total_rows,
        total_clients=total_clients,
        page=page,
        page_size=page_size,
        category_counts=category_counts,
        as_of=as_of,
    )


# ── Lista „Klienci”: jeden wiersz na klienta (makieta 19.11.2026) ───────────
# Decyzja Artura 19.11.2026 (wariant A): zakładki portfela ustawiane z manifestu
# albo ręcznym „Przenieś” były niezrozumiałe („czym są klienci relacyjni, czym
# jest »ręcznie«”) i nie mówiły prawdy — Tauron z dwiema otwartymi
# rekrutacjami stał w „Nieaktywnych”, a Nordea w dwóch zakładkach naraz. Stan
# na liście liczy się teraz z faktów; zakresy i ręczne ustawienia zostają
# w „Porządkach portfela” (``GET /directory`` powyżej, bez zmian).

_LIVE_CONTRACT_STATUSES = (ContractStatus.active, ContractStatus.ending)
_OPEN_SCOPE_CATEGORIES = (PortfolioCategory.active, PortfolioCategory.relationship)
CLIENT_LIST_STATES = ("working", "idle", "archive")


def _live_contracts_subquery():
    """Żywe kontrakty (aktywne i w wypowiedzeniu) per klient.

    Planowani = żywe minus obecne — ta sama para co „Obecni” i „Planowani”
    w profilu klienta, bez drugiej definicji „planowanego”.
    """

    return (
        select(
            Contract.client_id.label("client_id"),
            func.count(Contract.id).label("live_contracts"),
        )
        .where(Contract.status.in_(_LIVE_CONTRACT_STATUSES))
        .group_by(Contract.client_id)
        .subquery()
    )


def _open_jobs_subquery():
    """Otwarte rekrutacje per klient — ta sama reguła co profil (``published``)."""

    return (
        select(
            Job.client_id.label("client_id"),
            func.count(Job.id).label("open_jobs"),
        )
        .where(Job.status == JobStatus.published)
        .group_by(Job.client_id)
        .subquery()
    )


def _client_scopes_subquery():
    """Żywe zakresy portfela klienta zebrane do jednego wiersza."""

    effective_category = func.coalesce(
        ClientPortfolioScope.category_override,
        ClientPortfolioScope.category,
    )
    # Lustro `manuallyPlaced` z listy zakresów: zakładka inna niż w manifeście
    # albo przypięta data umowy (sama kolumna nadpisania równa manifestowi nie).
    manually_placed = or_(
        and_(
            ClientPortfolioScope.category_override.is_not(None),
            ClientPortfolioScope.category_override != ClientPortfolioScope.category,
        ),
        ClientPortfolioScope.contract_start_override.is_not(None),
        ClientPortfolioScope.contract_end_override.is_not(None),
    )
    return (
        select(
            ClientPortfolioScope.client_id.label("client_id"),
            func.bool_or(effective_category.in_(_OPEN_SCOPE_CATEGORIES)).label(
                "has_open_scope"
            ),
            func.bool_or(manually_placed).label("manually_placed"),
        )
        .where(ClientPortfolioScope.archived_at.is_(None))
        .group_by(ClientPortfolioScope.client_id)
        .subquery()
    )


def _client_list_base(
    *,
    as_of: date,
    allowed_client_ids: frozenset[int] | None,
):
    """Klienci z żywym zakresem portfela, z liczbami i stanem — podzapytanie.

    ``working`` = obecny albo planowany kontrakt, albo otwarta rekrutacja.
    Bez tego decyduje zakładka portfela: aktywni i relacyjni → ``idle``
    („Bez bieżącej pracy”), nieaktywni → ``archive``.
    """

    people = _active_consultants_subquery(as_of, by_scope=False)
    live = _live_contracts_subquery()
    jobs = _open_jobs_subquery()
    scopes = _client_scopes_subquery()

    current_contracts = func.coalesce(people.c.active_contracts, 0)
    planned = func.greatest(
        func.coalesce(live.c.live_contracts, 0) - current_contracts, 0
    )
    open_jobs = func.coalesce(jobs.c.open_jobs, 0)
    state = case(
        (or_(current_contracts > 0, planned > 0, open_jobs > 0), "working"),
        (scopes.c.has_open_scope.is_(True), "idle"),
        else_="archive",
    )

    statement = (
        select(
            Client.id.label("client_id"),
            _effective_client_name().label("display_name"),
            Client.legal_name.label("legal_name"),
            Client.industry.label("industry"),
            func.coalesce(people.c.active_consultants, 0).label("active_consultants"),
            planned.label("planned_consultants"),
            open_jobs.label("open_jobs"),
            state.label("state"),
            func.coalesce(scopes.c.manually_placed, False).label("manually_placed"),
        )
        .select_from(Client)
        .join(scopes, scopes.c.client_id == Client.id)
        .outerjoin(people, people.c.client_id == Client.id)
        .outerjoin(live, live.c.client_id == Client.id)
        .outerjoin(jobs, jobs.c.client_id == Client.id)
        .where(*_visible_client_filters())
    )
    if allowed_client_ids is not None:
        statement = statement.where(Client.id.in_(sorted(allowed_client_ids) or [-1]))
    return statement.subquery()


def _client_search_clause(client_id_column, q: str):
    """Ta sama wyszukiwarka co lista zakresów, ale po wszystkich stanach."""

    canonical_name = _effective_client_name()
    matching = select(Client.id).where(
        or_(
            polish_folded_ilike(canonical_name, q),
            polish_folded_ilike(Client.legal_name, q),
            polish_folded_ilike(Client.name, q),
            polish_folded_ilike(Client.industry, q),
            exists(
                select(ClientAlias.id).where(
                    ClientAlias.client_id == Client.id,
                    ClientAlias.archived_at.is_(None),
                    polish_folded_ilike(ClientAlias.alias, q),
                )
            ),
            exists(
                select(ClientPortfolioScope.id).where(
                    ClientPortfolioScope.client_id == Client.id,
                    ClientPortfolioScope.archived_at.is_(None),
                    polish_folded_ilike(ClientPortfolioScope.label, q),
                )
            ),
        )
    )
    return client_id_column.in_(matching)


def _client_list_rows_statement(base, *, state: str, q: Optional[str]):
    """Wiersze jednego stanu albo — przy frazie — wyniki ze wszystkich stanów."""

    normalized_q = (q or "").strip()
    statement = select(base)
    name_key = polish_alphabetical_key(base.c.display_name).asc()
    if normalized_q:
        statement = statement.where(
            _client_search_clause(base.c.client_id, normalized_q)
        )
        state_rank = case(
            (base.c.state == "working", 0),
            (base.c.state == "idle", 1),
            else_=2,
        )
        return statement.order_by(state_rank, name_key, base.c.client_id)
    statement = statement.where(base.c.state == state)
    if state == "working":
        # Najwięksi klienci na górze: tam najczęściej się wchodzi.
        return statement.order_by(
            base.c.active_consultants.desc(),
            base.c.planned_consultants.desc(),
            base.c.open_jobs.desc(),
            name_key,
            base.c.client_id,
        )
    return statement.order_by(name_key, base.c.client_id)


def _pick_framework_period(
    periods: list,
) -> tuple[Optional[date], Optional[date], bool]:
    """Umowa ramowa pokazywana w wierszu klienta z kilku zakresów.

    Bezterminowa wygrywa, potem najpóźniejszy koniec — to umowa, na której
    klient dziś stoi; pozostałe są liczone w ``framework_count``.
    """

    if not periods:
        return None, None, False
    open_ended = [period for period in periods if period.expiry_date is None]
    chosen = (
        open_ended[0]
        if open_ended
        else max(periods, key=lambda period: period.expiry_date)
    )
    return chosen.effective_date, chosen.expiry_date, True


async def _client_list_extras(
    db: AsyncSession,
    *,
    client_ids: list[int],
    finance_client_ids: frozenset[int],
    as_of: date,
    with_attention: bool,
) -> dict[int, dict]:
    """DL, umowa ramowa, „Wymaga uwagi” konsultantów i marża dla strony listy."""

    extras: dict[int, dict] = {
        client_id: {
            "delivery_leads": [],
            "framework": (None, None, False),
            "framework_count": 0,
            "attention": ClientListConsultantAttention(),
            "margin": None,
            "unpriced": 0,
        }
        for client_id in client_ids
    }
    if not client_ids:
        return extras

    lead_rows = await db.execute(
        select(
            DeliveryLeadClientAssignment.client_id,
            DeliveryLeadClientAssignment.is_head,
            User.name,
        )
        .join(User, User.id == DeliveryLeadClientAssignment.delivery_lead_user_id)
        .where(DeliveryLeadClientAssignment.client_id.in_(client_ids))
        .order_by(
            DeliveryLeadClientAssignment.client_id,
            DeliveryLeadClientAssignment.is_head.desc(),
            User.name,
        )
    )
    for row in lead_rows.all():
        extras[row.client_id]["delivery_leads"].append(
            ClientListDeliveryLead(name=row.name, is_head=bool(row.is_head))
        )

    # Zakres scalonego duplikatu zostaje na nim (inwariant manifestu), a umowa
    # idzie za scaleniem na klienta docelowego — wiersz celu bierze więc też
    # zakresy swoich duplikatów. Umowa liczy się, gdy należy do klienta wiersza
    # albo do klienta zakresu; zakres z umową przeniesioną do kogoś innego nie
    # udaje umowy bez terminu (porządki klientów 20.11.2026).
    scope_client = aliased(Client)
    row_client_id = func.coalesce(
        scope_client.merged_into_client_id, ClientPortfolioScope.client_id
    )
    period_rows = await db.execute(
        select(
            row_client_id.label("client_id"),
            func.coalesce(
                ClientPortfolioScope.contract_start_override,
                ClientFrameworkContract.effective_date,
            ).label("effective_date"),
            func.coalesce(
                ClientPortfolioScope.contract_end_override,
                ClientFrameworkContract.expiry_date,
            ).label("expiry_date"),
        )
        .select_from(ClientPortfolioScope)
        .join(scope_client, scope_client.id == ClientPortfolioScope.client_id)
        .outerjoin(
            ClientFrameworkContract,
            and_(
                ClientFrameworkContract.id
                == ClientPortfolioScope.framework_contract_id,
                or_(
                    ClientFrameworkContract.client_id == ClientPortfolioScope.client_id,
                    ClientFrameworkContract.client_id == row_client_id,
                ),
            ),
        )
        .where(
            row_client_id.in_(client_ids),
            ClientPortfolioScope.archived_at.is_(None),
            or_(
                ClientFrameworkContract.id.is_not(None),
                ClientPortfolioScope.contract_start_override.is_not(None),
                ClientPortfolioScope.contract_end_override.is_not(None),
            ),
        )
    )
    periods_by_client: dict[int, list] = {}
    for row in period_rows.all():
        periods_by_client.setdefault(row.client_id, []).append(row)
    for client_id, periods in periods_by_client.items():
        extras[client_id]["framework"] = _pick_framework_period(periods)
        extras[client_id]["framework_count"] = len(periods)

    need_contracts = (
        client_ids
        if with_attention
        else [cid for cid in client_ids if cid in finance_client_ids]
    )
    if not need_contracts:
        return extras
    loads = [*RATE_SCHEDULE_LOADS]
    if with_attention:
        loads.append(
            selectinload(Contract.client_orders).selectinload(ClientOrder.order_group)
        )
    contracts = list(
        (
            await db.execute(
                select(Contract)
                .options(*loads)
                .where(
                    Contract.client_id.in_(need_contracts),
                    Contract.status.in_(_LIVE_CONTRACT_STATUSES),
                )
            )
        ).scalars()
    )
    current_by_client: dict[int, list[Contract]] = {}
    for contract in await load_current_contracts(db, contracts, as_of):
        current_by_client.setdefault(contract.client_id, []).append(contract)

    for client_id, current in current_by_client.items():
        if with_attention:
            # Te same znaczniki co podzakładka „Wymaga uwagi” w Konsultantach
            # profilu: liczone wyłącznie u obecnych (planowanych nie oznaczamy).
            attention = extras[client_id]["attention"]
            for contract in current:
                state = consultant_order_state(contract, as_of, is_current=True)
                if not state.attention:
                    continue
                attention.total += 1
                if ATTENTION_ORDER_ENDING in state.attention:
                    attention.order_ending += 1
                    ending_on = state.order_ending_on
                    if ending_on is not None and (
                        attention.order_ending_first is None
                        or ending_on < attention.order_ending_first
                    ):
                        attention.order_ending_first = ending_on
                if ATTENTION_NO_CURRENT_ORDER in state.attention:
                    attention.no_current_order += 1
                if ATTENTION_NOTICE in state.attention:
                    attention.notice += 1
        if client_id in finance_client_ids:
            totals = await _monthly_margin_total_pln(db, current, as_of)
            # Lustro „Aktywnego MRR” profilu: bez kompletu kursów albo bez
            # żadnej wycenionej marży u obecnych konsultantów — brak liczby.
            if totals.complete and totals.has_margin:
                extras[client_id]["margin"] = int(totals.margin)
            extras[client_id]["unpriced"] = totals.unpriced
    for client_id in finance_client_ids:
        if client_id in extras and client_id not in current_by_client:
            extras[client_id]["margin"] = 0
    return extras


def _client_list_item(row, extras: dict, *, can_view_legal: bool) -> ClientListItem:
    effective_date, expiry_date, has_period = extras["framework"]
    return ClientListItem(
        client_id=row.client_id,
        display_name=row.display_name,
        legal_name=row.legal_name if can_view_legal else None,
        industry=row.industry,
        state=row.state,
        active_consultants=int(row.active_consultants or 0),
        planned_consultants=int(row.planned_consultants or 0),
        open_jobs=int(row.open_jobs or 0),
        monthly_margin=extras["margin"],
        monthly_margin_unpriced=extras["unpriced"],
        delivery_leads=extras["delivery_leads"],
        framework_effective_date=effective_date,
        framework_expiry_date=expiry_date,
        has_framework_period=has_period,
        framework_count=extras["framework_count"],
        consultant_attention=extras["attention"],
        manually_placed=bool(row.manually_placed),
    )


async def _list_finance_ids(
    user: User, db: AsyncSession, client_ids: list[int]
) -> frozenset[int]:
    return list_finance_client_ids(
        user,
        client_ids,
        delivery_lead_finance_client_ids=await resolve_delivery_lead_finance_client_ids(
            user, db
        ),
    )


@router.get("/directory/clients", response_model=ClientListResponse)
async def list_clients_by_state(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    state: str = Query("working", pattern="^(working|idle|archive)$"),
    q: Optional[str] = Query(None, max_length=200),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=100),
    mine: bool = Query(False),
):
    """Lista „Klienci”: jeden wiersz na klienta, stan liczony z faktów.

    Fraza szuka we wszystkich stanach (wiersz niesie swój ``state``); liczniki
    stanów nie zależą od frazy. Kwoty (marża miesięczna) tą samą regułą co
    „Moi klienci”: ``list_finance_client_ids``.
    """

    as_of = business_today()
    allowed_client_ids = await _directory_client_scope(current_user, db, mine=mine)
    base = _client_list_base(as_of=as_of, allowed_client_ids=allowed_client_ids)
    rows_statement = _client_list_rows_statement(base, state=state, q=q)
    total = int(
        (
            await db.execute(
                select(func.count()).select_from(
                    rows_statement.order_by(None).subquery()
                )
            )
        ).scalar_one()
    )
    rows = (
        await db.execute(rows_statement.offset((page - 1) * page_size).limit(page_size))
    ).all()
    client_ids = [row.client_id for row in rows]
    finance_client_ids = await _list_finance_ids(current_user, db, client_ids)
    extras = await _client_list_extras(
        db,
        client_ids=client_ids,
        finance_client_ids=finance_client_ids,
        as_of=as_of,
        with_attention=True,
    )
    can_view_legal = _can_view_directory_legal(current_user)
    items = [
        _client_list_item(row, extras[row.client_id], can_view_legal=can_view_legal)
        for row in rows
    ]

    counts = dict.fromkeys(CLIENT_LIST_STATES, 0)
    for state_value, count in (
        await db.execute(select(base.c.state, func.count()).group_by(base.c.state))
    ).all():
        counts[state_value] = int(count)
    manually_placed_count = int(
        (
            await db.execute(
                select(func.count())
                .select_from(base)
                .where(base.c.manually_placed.is_(True))
            )
        ).scalar_one()
    )

    return ClientListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        state_counts=ClientListStateCounts(**counts),
        amounts_visible=bool(finance_client_ids),
        manually_placed_count=manually_placed_count,
        as_of=as_of,
    )


_CLIENT_STATE_LABELS = {
    "working": "Współpracujemy",
    "idle": "Bez bieżącej pracy",
    "archive": "Archiwum",
}


@router.get("/directory/clients/export", dependencies=NOT_READ_ONLY)
async def export_clients_by_state(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    state: str = Query("working", pattern="^(working|idle|archive)$"),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(10000, ge=1, le=50000),
    mine: bool = Query(False),
):
    """Eksport listy „Klienci” — to, co widać na ekranie, bez stronicowania.

    Marża tylko u klientów, których kwoty ta osoba widzi na liście; kolumny
    prawne tylko dla ról, które widzą je w katalogu. Eksport nie poszerza dostępu.
    """

    as_of = business_today()
    base = _client_list_base(
        as_of=as_of,
        allowed_client_ids=await _directory_client_scope(current_user, db, mine=mine),
    )
    rows = (
        await db.execute(
            _client_list_rows_statement(base, state=state, q=q).limit(limit)
        )
    ).all()
    truncated = len(rows) >= limit
    client_ids = [row.client_id for row in rows]
    finance_client_ids = await _list_finance_ids(current_user, db, client_ids)
    extras = await _client_list_extras(
        db,
        client_ids=client_ids,
        finance_client_ids=finance_client_ids,
        as_of=as_of,
        with_attention=False,
    )
    can_view_legal = _can_view_directory_legal(current_user)
    show_margin = bool(finance_client_ids)

    columns = [
        "ID klienta",
        "Klient",
        "Stan",
        "Nasi ludzie u klienta",
        "Zaczynają",
        "Otwarte rekrutacje",
    ]
    if show_margin:
        columns.append("Marża / mc (PLN)")
    columns += ["Umowa ramowa od", "Umowa ramowa do", "Delivery Lead", "Branża"]
    if can_view_legal:
        columns.append("Nazwa prawna")

    data_rows = []
    for row in rows:
        item = _client_list_item(
            row, extras[row.client_id], can_view_legal=can_view_legal
        )
        values: list = [
            item.client_id,
            item.display_name,
            _CLIENT_STATE_LABELS[item.state],
            item.active_consultants,
            item.planned_consultants,
            item.open_jobs,
        ]
        if show_margin:
            values.append("" if item.monthly_margin is None else item.monthly_margin)
        values += [
            item.framework_effective_date.isoformat()
            if item.framework_effective_date
            else "",
            (
                ""
                if not item.has_framework_period
                else item.framework_expiry_date.isoformat()
                if item.framework_expiry_date
                else "Bezterminowa"
            ),
            ", ".join(lead.name for lead in item.delivery_leads),
            item.industry or "",
        ]
        if can_view_legal:
            values.append(item.legal_name or "")
        data_rows.append([safe_cell(value) for value in values])

    return _directory_file_response(
        columns, data_rows, format=format, truncated=truncated, stem="klienci"
    )


def _directory_file_response(
    columns: list[str],
    data_rows: list[list],
    *,
    format: str,
    truncated: bool,
    stem: str,
) -> StreamingResponse:
    """Plik XLSX albo CSV (z BOM dla Excela) z nagłówkiem ``X-Export-Truncated``."""

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    headers_extra = {"X-Export-Truncated": "true"} if truncated else {}
    if format == "xlsx":
        from openpyxl import Workbook
        from openpyxl.styles import Font

        wb = Workbook()
        ws = wb.active
        ws.title = "Klienci"
        ws.append(columns)
        for cell in ws[1]:
            cell.font = Font(bold=True)
        ws.freeze_panes = "A2"
        for data_row in data_rows:
            ws.append(data_row)
        buf = BytesIO()
        wb.save(buf)
        buf.seek(0)
        return StreamingResponse(
            buf,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={
                "Content-Disposition": f'attachment; filename="{stem}_{ts}.xlsx"',
                **headers_extra,
            },
        )

    import csv
    from io import StringIO

    text = StringIO()
    writer = csv.writer(text, quoting=csv.QUOTE_MINIMAL)
    writer.writerow(columns)
    for data_row in data_rows:
        writer.writerow(data_row)
    return StreamingResponse(
        iter(["﻿" + text.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{stem}_{ts}.csv"',
            **headers_extra,
        },
    )


# ── Export (CSV / XLSX) ───────────────────────────────────────────────────────
# Business-facing Polish labels for the enum columns — the directory export
# lands in delivery / finance spreadsheets, so we render labels instead of the
# raw enum values.
_CATEGORY_LABELS = {
    "active": "Aktywny",
    "relationship": "Relacyjny",
    "inactive": "Nieaktywny",
}
_CLIENT_STATUS_LABELS = {
    "active": "Aktywny",
    "inactive": "Nieaktywny",
    "prospect": "Prospekt",
}

# Columns every operational user may export — mirror the on-screen directory.
_DIRECTORY_EXPORT_BASE_COLUMNS = [
    "ID klienta",
    "Klient",
    "Zakres",
    "Kategoria",
    "Branża",
    "Status klienta",
    "Aktywni konsultanci",
    "Aktywne kontrakty",
    "Start umowy ramowej",
    "Koniec umowy ramowej",
]
# Legal columns — only for roles that already see legal data in Delivery
# (Admin / Finance / assigned Delivery Lead). The export never widens access.
_DIRECTORY_EXPORT_LEGAL_COLUMNS = ["Nazwa prawna", "NIP", "REGON"]


def _directory_enum_label(value, labels: dict) -> str:
    """Polish label for an enum value; falls back to the raw value, "" for None."""
    if value is None:
        return ""
    raw = value.value if hasattr(value, "value") else str(value)
    return labels.get(raw, raw)


def _directory_contract_end_cell(row) -> str:
    """Mirror the UI's "Koniec umowy" column: a scope with no contract period
    (no MSA and no manual date override) has no contract end, while a contract
    period with no end date is open-ended. ``expiry_date`` is already the
    effective (override-preferring) value."""
    if not row.has_contract_period:
        return ""
    if row.expiry_date is None:
        return "Bezterminowa"
    return row.expiry_date.isoformat()


# Osłona przed wstrzyknięciem formuły: display_name / scope_label / industry /
# legal_name to wartości wpisywane przez ludzi — `safe_cell` (app.core.export_safety).
def _directory_export_row(row, *, can_view_legal: bool) -> list:
    values = [
        row.client_id,
        row.display_name or "",
        row.scope_label or "",
        _directory_enum_label(row.category, _CATEGORY_LABELS),
        row.industry or "",
        _directory_enum_label(row.client_status, _CLIENT_STATUS_LABELS),
        int(row.active_consultants_count or 0),
        int(row.active_contracts_count or 0),
        row.effective_date.isoformat() if row.effective_date else "",
        _directory_contract_end_cell(row),
    ]
    if can_view_legal:
        values.extend([row.legal_name or "", row.nip or "", row.regon or ""])
    return [safe_cell(value) for value in values]


@router.get("/directory/export", dependencies=NOT_READ_ONLY)
async def export_client_directory(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
    format: str = Query("xlsx", pattern="^(csv|xlsx)$"),
    category: PortfolioCategory = Query(PortfolioCategory.active),
    q: Optional[str] = Query(None, max_length=200),
    limit: int = Query(10000, ge=1, le=50000),
    mine: bool = Query(False),
):
    """Export the client directory to CSV or Excel — one row per portfolio scope.

    Honours the same ``category`` + ``q`` filters as the list endpoint (so
    "eksportuj to, co widzę" holds) but ignores pagination — every matching row
    up to ``limit``. Legal columns (Nazwa prawna / NIP / REGON) appear only for
    roles that already see them in the directory; the export never widens access.
    """
    can_view_legal = _can_view_directory_legal(current_user)
    statement = _directory_rows_statement(
        category=category,
        q=q,
        as_of=business_today(),
        allowed_client_ids=await _directory_client_scope(current_user, db, mine=mine),
    ).limit(limit)
    rows = (await db.execute(statement)).all()
    # Hitting ``limit`` means the file may be a partial view. Signal it in a
    # header (rather than silently) so the caller can warn — the FE surfaces a
    # toast. Realistic directories sit far below the 10k default, so this is a
    # safety net, not an expected path.
    truncated = len(rows) >= limit

    columns = list(_DIRECTORY_EXPORT_BASE_COLUMNS)
    if can_view_legal:
        columns += _DIRECTORY_EXPORT_LEGAL_COLUMNS
    data_rows = [
        _directory_export_row(row, can_view_legal=can_view_legal) for row in rows
    ]
    return _directory_file_response(
        columns, data_rows, format=format, truncated=truncated, stem="klienci"
    )


async def _get_scope_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(
        select(Client).where(
            Client.id == client_id,
            *_visible_client_filters(),
        )
    )
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return client


async def _get_active_scope(
    db: AsyncSession,
    *,
    client_id: int,
    scope_id: int,
) -> ClientPortfolioScope:
    scope = await db.scalar(
        select(ClientPortfolioScope).where(
            ClientPortfolioScope.id == scope_id,
            ClientPortfolioScope.client_id == client_id,
            ClientPortfolioScope.archived_at.is_(None),
        )
    )
    if scope is None:
        raise HTTPException(status_code=404, detail="Portfolio scope not found")
    return scope


async def _validate_framework_contract(
    db: AsyncSession,
    *,
    client_id: int,
    framework_contract_id: Optional[int],
    exclude_scope_id: Optional[int] = None,
) -> None:
    if framework_contract_id is None:
        return
    contract_id = await db.scalar(
        select(ClientFrameworkContract.id).where(
            ClientFrameworkContract.id == framework_contract_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if contract_id is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Framework contract does not belong to this client",
        )
    occupied = select(ClientPortfolioScope.id).where(
        ClientPortfolioScope.framework_contract_id == framework_contract_id,
        ClientPortfolioScope.archived_at.is_(None),
    )
    if exclude_scope_id is not None:
        occupied = occupied.where(ClientPortfolioScope.id != exclude_scope_id)
    occupied_scope_id = await db.scalar(occupied)
    if occupied_scope_id is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        )


@router.post(
    "/{client_id}/portfolio-scopes",
    response_model=ClientPortfolioScopeResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_client_portfolio_scope(
    client_id: int,
    payload: ClientPortfolioScopeCreate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    await _validate_framework_contract(
        db,
        client_id=client_id,
        framework_contract_id=payload.framework_contract_id,
    )

    scope = ClientPortfolioScope(
        client_id=client_id,
        framework_contract_id=payload.framework_contract_id,
        category=payload.category,
        label=payload.label,
        source_system="manual",
    )
    db.add(scope)
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        ) from exc
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_created",
            user_id=current_user.id,
            details={
                "scope_id": scope.id,
                "category": payload.category.value,
            },
        )
    )
    await db.flush()
    await db.refresh(scope)
    return ClientPortfolioScopeResponse.model_validate(scope)


@router.patch(
    "/{client_id}/portfolio-scopes/{scope_id}",
    response_model=ClientPortfolioScopeResponse,
)
async def update_client_portfolio_scope(
    client_id: int,
    scope_id: int,
    payload: ClientPortfolioScopeUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return ClientPortfolioScopeResponse.model_validate(scope)

    # Manifest-owned scopes must not have their invariant columns rewritten in
    # place: ``get_client_portfolio_import_health`` compares live ``category`` /
    # ``framework_contract_id`` against the applied import rows, so an in-place
    # edit here reports the portfolio import as unhealthy (/api/health/deep 503)
    # and never self-heals on restart. Curate those through the placement
    # override (PATCH …/placement) instead; ``label`` stays freely editable.
    if scope.source_system != "manual" and (
        "category" in updates or "framework_contract_id" in updates
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ten zakres pochodzi z manifestu portfela — zmiana kategorii "
                "lub umowy w miejscu rozjechałaby stan z manifestem. Użyj akcji "
                "„Przenieś w portfelu” (nakładka placementu)."
            ),
        )

    if "framework_contract_id" in updates:
        await _validate_framework_contract(
            db,
            client_id=client_id,
            framework_contract_id=updates["framework_contract_id"],
            exclude_scope_id=scope.id,
        )

    for field, value in updates.items():
        setattr(scope, field, value)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_updated",
            user_id=current_user.id,
            details={"scope_id": scope.id, "fields": sorted(updates)},
        )
    )
    try:
        await db.flush()
    except IntegrityError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Framework contract already belongs to an active portfolio scope",
        ) from exc
    await db.refresh(scope)
    return ClientPortfolioScopeResponse.model_validate(scope)


@router.patch(
    "/{client_id}/portfolio-scopes/{scope_id}/placement",
    response_model=ClientPortfolioScopeResponse,
)
async def update_client_portfolio_scope_placement(
    client_id: int,
    scope_id: int,
    payload: ClientPortfolioScopePlacementUpdate,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    """Curate a scope's directory placement without touching the manifest.

    Writes only the ``*_override`` columns, which the directory READ prefers but
    the manifest consistency invariant ignores. This is the safe way to move a
    client between the Aktywni/Relacyjni/Nieaktywni tabs or pin a contract
    period for a manifest-owned scope — it never causes portfolio drift. A field
    sent as ``null`` clears that override (the row falls back to the manifest /
    linked MSA); an absent field is left unchanged.
    """

    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        return ClientPortfolioScopeResponse.model_validate(scope)

    # Validate the PROSPECTIVE override pair (incoming value or the existing one
    # for an omitted field) BEFORE mutating the ORM object. Mutating first would
    # let an autoflush persist an incoherent pair and surface as an
    # IntegrityError/500 instead of this clean 422 — and it also covers the
    # partial-update case (one date already pinned, the other now sent).
    new_start = (
        updates["contract_start"]
        if "contract_start" in updates
        else scope.contract_start_override
    )
    new_end = (
        updates["contract_end"]
        if "contract_end" in updates
        else scope.contract_end_override
    )
    if new_start is not None and new_end is not None and new_end < new_start:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Data zakończenia umowy nie może być wcześniejsza niż rozpoczęcia.",
        )

    if "category" in updates:
        scope.category_override = updates["category"]
    if "contract_start" in updates:
        scope.contract_start_override = updates["contract_start"]
    if "contract_end" in updates:
        scope.contract_end_override = updates["contract_end"]

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_placement_updated",
            user_id=current_user.id,
            details={"scope_id": scope.id, "fields": sorted(updates)},
        )
    )
    await db.flush()
    await db.refresh(scope)
    return ClientPortfolioScopeResponse.model_validate(scope)


@router.delete(
    "/{client_id}/portfolio-scopes/{scope_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def archive_client_portfolio_scope(
    client_id: int,
    scope_id: int,
    current_user: AdminUser,
    db: AsyncSession = Depends(get_db),
):
    await _get_scope_client(db, client_id)
    scope = await _get_active_scope(db, client_id=client_id, scope_id=scope_id)
    # Archiving a manifest-owned scope removes it from the live invariant join
    # entirely (live_portfolio_scopes < audit_rows) → /api/health/deep 503 with
    # no self-heal — this is exactly the 2026-08-03 outage. Manifest scopes are
    # curated via the placement override; true removal goes through the manifest.
    if scope.source_system != "manual":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Ten zakres pochodzi z manifestu portfela — archiwizacja z UI "
                "rozjechałaby stan z manifestem. Zmień kategorię/umowę akcją "
                "„Przenieś w portfelu”; trwałe usunięcie zrób przez manifest."
            ),
        )
    scope.archived_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="portfolio_scope_archived",
            user_id=current_user.id,
            details={"scope_id": scope.id},
        )
    )
    await db.flush()
