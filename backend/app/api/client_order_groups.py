"""Router `/api/clients/{client_id}/order-groups` — zamówienia wielo-konsultantowe.

Grupa to „Zamówienie nr 445" od klienta; linia to konkretny konsultant pod tym
numerem, ze swoją stawką kosztową, przychodową i budżetem MD. Linia jest
zwykłym ``ClientOrder`` wpiętym w grupę, więc zachowuje kontrakt, kandydata i
całą dotychczasową obsługę (skaner wygasania, sync terminacji, MRR).

Cały router stoi za bramką klientów (``MULTI_CONSULTANT_ORDER_CLIENT_IDS``).
Bramka jest przy KAŻDEJ operacji, nie tylko przy renderowaniu widoku: ukryty
przycisk nie jest zabezpieczeniem, a wywołane wprost API założyłoby zamówienie
u klienta, którego zakładka nigdy go nie pokaże — czyli dane nie do zobaczenia
i nie do poprawienia z interfejsu.

Obsadę zamówienia prowadzi **delivery**: operacyjny rejestr obejmuje wszystkich
klientów, ale stawki linii MD ustawia admin albo Delivery Lead przypisany do
klienta (``_has_md_line_management_access``). To
świadome poszerzenie względem modułu zamówień, gdzie ``rate_client`` /
``rate_candidate`` zostają admin-only — tamte pola są interpretowane przez
``Contract.rate_unit`` i zasilają marżę miesięczną wszystkich klientów, te są
per MD i dotyczą wyłącznie tej powierzchni.
"""

from __future__ import annotations

import io
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from starlette.concurrency import run_in_threadpool
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.financial_access import has_financial_access
from app.api.deps import (
    DeliveryLeadOrAdmin,
    get_current_user,
    require_delivery_lead_or_admin,
    require_roles,
)
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import (
    GROUP_STATUS_ACTIVE,
    GROUP_STATUS_COMPLETED,
    GROUP_STATUS_EXHAUSTED,
    GROUP_STATUS_SCHEDULED,
    GROUP_STATUS_LABELS,
    ClientOrderGroup,
    ClientOrderGroupEvent,
    ClientOrderGroupMdConsumption,
)
from app.models.client_order_offboarding import (
    OFFBOARDING_RATE_BASIS_DEPARTING,
    OFFBOARDING_RESOLUTION_REMOVE,
    OFFBOARDING_RESOLUTION_RESTORE,
    OFFBOARDING_RESOLUTION_TRANSFER,
    OFFBOARDING_STATUS_PENDING,
    OFFBOARDING_STATUS_RESOLVED,
    ClientOrderOffboardingCase,
)
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
    MdConsumptionImport,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.job import Job
from app.models.order_type import OrderType
from app.models.user import User, UserRole
from app.services.access_scope import resolve_delivery_lead_finance_client_ids
from app.schemas.client_order_group import (
    ConsultantOptionRead,
    ConsultantOptionsResponse,
    OrderDraftRead,
    OrderGroupClose,
    OrderGroupCreate,
    OrderGroupExtend,
    OrderGroupEventRead,
    OrderGroupEventsResponse,
    OrderGroupExportRequest,
    OrderGroupListResponse,
    OrderGroupRead,
    OrderGroupUpdate,
    OrderLineCreate,
    OrderOffboardingCaseRead,
    OrderOffboardingResolutionRequest,
    OrderLineRead,
    OrderLineSwapRequest,
    OrderLineUpdate,
)
from app.services.client_identity import client_display_name
from app.services.client_order_lines import (
    CLIENT_CONTRACT_STATUSES,
    _line_query,
    consultant_display_name,
    lines_for_group,
    list_consultant_options,
    record_event,
    recompute_remaining,
    sync_md_line_status,
)
from app.services.client_access import deny, resolve_client_access
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.cost_orders import (
    assert_cost_order_client,
    hides_standard_drafts_from_order_group_registry,
    lock_group_for_settlement,
    quantize_money,
    settle_group,
)
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.order_engagement_separation import absorb_auto_draft_shells
from app.services.cyfrowy_polsat_orders import (
    is_cyfrowy_polsat_order_types_client,
)
from app.services.dl_alerts import (
    emit_cost_order_exhausted,
    emit_shared_md_pool_exhausted,
    handle_offboarding_case_alerts,
)
from app.services.lotte_wedel_orders import is_lotte_wedel_order_types_client
from app.services.multi_consultant_orders import (
    EVENT_BUDGET_EXHAUSTED,
    EVENT_CONSULTANT_ADDED,
    EVENT_CONSULTANT_SWAPPED,
    EVENT_MANUAL_EDIT,
    EVENT_MD_TRANSFER,
    EVENT_MD_OFFBOARDING_REMOVED,
    EVENT_MD_OFFBOARDING_RESTORED,
    EVENT_MD_OFFBOARDING_TRANSFERRED,
    EVENT_ORDER_CLOSED,
    EVENT_ORDER_CREATED,
    EVENT_ORDER_EXTENDED,
    EVENT_ORDER_REOPENED,
    EVENT_TYPE_LABELS,
    INPUT_MODE_AMOUNT,
    INPUT_MODE_MD,
    compute_md_total,
    format_md,
    is_multi_consultant_client,
    quantize_md,
    remaining_value_pln,
    swap_md_total,
)
from app.services.order_group_lifecycle import materialize_scheduled_order_groups
from app.services.order_write_errors import commit_order_write
from app.services.order_types import (
    assert_order_type_allowed,
    effective_group_order_type,
    suggested_order_type,
)
from app.services.fx_service import rates_to_pln
from app.services.order_rate_snapshots import convert_order_rate
from app.services.shared_md_orders import (
    upsert_shared_md_consumption,
    client_uses_shared_md_pool,
    normalize_empty_generic_explicit_md_group,
    settle_shared_md_group,
    shared_md_used_total,
    shared_md_used_totals,
    uses_shared_md_pool,
)
from app.services.order_excel_export import (
    OrderExportRow,
    build_orders_workbook,
    export_rows_for_group,
    orders_export_filename,
)
from app.services import storage_service

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

MAX_GROUP_PDF_BYTES = 25 * 1024 * 1024

# Nazwy KOLUMN, którymi `update_order_group` opisuje własną edycję. Wpis
# `edycja_reczna` zawierający wyłącznie takie nazwy jest zapisem technicznym —
# mówi „zmieniono end_date", a nie co się stało z zamówieniem — i historia
# zamówienia go nie pokazuje.
#
# Ukrywamy PRZY ODCZYCIE, nigdy przez zawężenie domeny CHECK-a ani przez
# usunięcie etykiety: na produkcji istnieją wiersze obu typów, więc węższy
# CHECK nie dałby się założyć (precedens 0226), a brak etykiety wyrenderowałby
# historyczny wpis surowym slugiem. Wpisy `edycja_reczna` z etykietami
# biznesowymi („stawka kosztowa", „budżet MD") ZOSTAJĄ widoczne — na tej samej
# grupie istnieją oba kształty.
_TECHNICAL_EDIT_FIELDS = frozenset(
    {
        "order_number",
        "start_date",
        "end_date",
        "notes",
        "budget_amount",
        "budget_manual_adjustment",
        "md_budget_total",
        "md_budget_manual_adjustment",
    }
)


def _is_technical_event(event_type: str, payload: Optional[dict]) -> bool:
    """Czy ten wpis jest zapisem technicznym, którego historia nie pokazuje."""
    if event_type == EVENT_ORDER_EXTENDED:
        # „Zamówienie X przedłuża zamówienie Y" — ten fakt niesie już samo
        # zagnieżdżenie kart, więc w dzienniku jest szumem.
        return True
    if event_type != EVENT_MANUAL_EDIT:
        return False
    changed = (payload or {}).get("changed")
    if not isinstance(changed, list):
        # Nieznany kształt zostaje widoczny: ukrywanie tego, czego nie umiemy
        # rozpoznać, kasuje z raportu wpisy starsze od tej reguły.
        return False
    return set(changed) <= _TECHNICAL_EDIT_FIELDS


# Pola pieniężne grupy i linii. Nazwy są WŁASNE, nie z
# `_ORDER_FINANCE_WRITE_FIELDS`
# w `client_orders.py` — tamten zbiór opisuje `rate_client`/`rate_candidate`,
# czyli stawki interpretowane przez `Contract.rate_unit`. Tutaj stawki są
# per MD i mają osobne kolumny, więc muszą mieć też własną bramkę; użycie
# tamtego zbioru przepuściłoby te pola bez żadnej kontroli.
_GROUP_FINANCE_FIELDS = frozenset(
    {
        "rate_candidate_currency",
        "rate_client_currency",
        "rate_cost",
        "rate_revenue",
        "budget_amount",
        "budget_manual_adjustment",
        "md_budget_total",
        "md_budget_manual_adjustment",
    }
)


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _canonical_currency_rate(
    db: AsyncSession, value: Decimal, currency: str, on: date
) -> Decimal:
    fx = await rates_to_pln(db, {currency}, on)
    factor = fx.get(currency)
    if factor is None:
        raise HTTPException(422, detail=f"Brak kursu {currency}/PLN")
    return (value * factor).quantize(Decimal("0.01"))


async def _assert_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    return client


async def _require_group_read(db: AsyncSession, user: User, client_id: int) -> None:
    """Ta sama decyzja dostępu co przy zamówieniach jednoosobowych.

    Lustro ``client_orders._require_client_order_read``: Delivery Lead widzi
    operacyjny rekord każdego klienta, a serializer osobno redaguje stawki poza
    przypisanym portfelem. Finance ma organizacyjny business-read.
    """
    await _assert_client(db, client_id)
    # Finance ma organizacyjny odczyt. Head of Recruitment nie omija już
    # granicy klienta, a na poziomie sekcji w ogóle nie wchodzi do Delivery.
    if user.has_role(UserRole.finance) and has_financial_access(user):
        return
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają dostępu operacyjnego Delivery")


async def _require_safe_group_read(
    db: AsyncSession,
    user: User,
    client_id: int,
) -> None:
    """Authorize the structured, finance-redacted order-group projection."""

    await _assert_client(db, client_id)
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_knowledge:
        raise deny("zamówienia klienta wymagają dostępu operacyjnego do klienta")


def _is_read_only_tcm(user: User) -> bool:
    """TCM ceiling for Delivery orders, irrespective of HoR/TAC secondary roles.

    HoR and TAC do not independently enter Delivery, so only Admin, Delivery
    Lead, or Finance can supersede the TCM read-only projection here.
    """

    return user.has_role(UserRole.talent_community_manager) and not user.has_any_role(
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.finance,
    )


def _redact_group_document_metadata(group: OrderGroupRead) -> OrderGroupRead:
    """Hide PO-file affordances from the non-document TCM projection."""

    group.filename = None
    group.has_file = False
    group.content_type = None
    group.size_bytes = None
    group.file_uploaded_at = None
    for future in group.future_orders:
        _redact_group_document_metadata(future)
    return group


def _assert_multi_client(client_id: int) -> None:
    """Kompatybilny punkt bramkowania — grupy są od teraz globalne.

    Uprawnienia nadal sprawdzają zależność użytkownik-klient. Historyczna lista
    klientów pozostaje używana tylko przez stare automaty i matchery.
    """
    return None


def _has_md_line_management_role(user: User) -> bool:
    """Czy ROLA użytkownika prowadzi linie MD: admin albo Delivery Lead.

    **Nazwa mówi „rola" celowo — ta funkcja NIE sprawdza klienta.** Każdy zapis
    kwoty musi dodatkowo przejść przez ``_has_md_line_management_access``, który
    sprawdza finansowy zakres przypisań.

    Delivery jest tu CELOWO, mimo że nie ma ``VIEW_FINANCE``: to delivery układa
    obsadę zamówienia i negocjuje stawki per konsultant, a wymóg admina do
    dodania konsultanta czynił tę zakładkę bezużyteczną dla osób, które
    faktycznie ją obsługują.

    Zakres jest wąski i tego trzeba pilnować:

    * tylko kolumny ``md_rate_cost`` / ``md_rate_revenue`` na TEJ powierzchni —
      legacy ``rate_client`` / ``rate_candidate`` / ``total_value`` w module
      zamówień zostają admin-only (``_ORDER_FINANCE_WRITE_FIELDS``),
    * tylko klient, do którego DL jest jawnie przypisany — pilnuje tego
      ``_has_md_line_management_access`` w guardzie pola,
    * **head_of_recruitment NIE** — bramka sekcji Delivery odcina tę rolę,
      a przy powierzchniach finansowych repo konsekwentnie trzyma ją poza,
    * rola ``finance`` NIE zapisuje stawek linii MD, ale widzi je przez osobny
      ``_can_see_finance`` i capability ``VIEW_FINANCE``.

    Odczyt i zapis są celowo rozdzielone: role zapisujące nadal widzą stawki,
    a Finance ma wyłącznie organizacyjny odczyt.
    """
    # Sam test roli. Przypisanie do klienta sprawdza osobny helper access.
    return user.has_any_role(UserRole.admin, UserRole.delivery_lead)


async def _has_md_line_management_access(
    db: AsyncSession,
    user: User,
    client_id: int,
) -> bool:
    """Keep the MD-rate exception inside the DL's assigned finance portfolio."""

    if user.has_role(UserRole.admin):
        return True
    if not user.has_role(UserRole.delivery_lead):
        return False
    finance_client_ids = await resolve_delivery_lead_finance_client_ids(user, db)
    return finance_client_ids is not None and client_id in finance_client_ids


async def _assert_no_pending_offboarding_case(
    db: AsyncSession,
    *,
    group_id: int,
    order_id: Optional[int] = None,
) -> None:
    """Block ordinary mutations that could orphan/version-skew a DL decision."""

    query = select(ClientOrderOffboardingCase.id).where(
        ClientOrderOffboardingCase.order_group_id == group_id,
        ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
    )
    if order_id is not None:
        query = query.where(ClientOrderOffboardingCase.order_id == order_id)
    if await db.scalar(query.limit(1)) is not None:
        raise HTTPException(
            409,
            detail={
                "code": "offboarding_decision_required",
                "message": (
                    "Najpierw podejmij decyzję o pozostałej puli MD po "
                    "zakończeniu współpracy konsultanta."
                ),
            },
        )


def _reduce_legacy_md_budget(order: ClientOrder, remaining: Decimal) -> None:
    """Lower the signed line budget by the forfeited/transferred remainder.

    Keeping the old total and merely offsetting ``md_manual_adjustment`` made
    exports and cards claim that the unused MD had been consumed.  Reducing
    the source total represents the requested decrease in order value while
    consumption rows and historical adjustments remain intact.
    """

    if order.md_total is None or remaining <= 0:
        return
    rate_revenue = (
        None if order.md_rate_revenue is None else Decimal(str(order.md_rate_revenue))
    )
    if (
        order.md_input_mode not in {INPUT_MODE_AMOUNT, INPUT_MODE_MD}
        or order.md_input_value is None
        or rate_revenue is None
        or rate_revenue <= 0
    ):
        # Migracyjne CHECK-i legacy są celowo NOT VALID. Nie wolno więc
        # polegać wyłącznie na bazie ani próbować zgadywać brakującej stawki:
        # kwota mogłaby zostać zapisana jako MD albo częściowo zmieniony rekord
        # mógłby zakończyć transakcję błędem 500. Zatrzymaj decyzję DL przed
        # pierwszą mutacją i pozostaw case do ręcznej korekty danych.
        raise HTTPException(
            status_code=409,
            detail={
                "code": "invalid_legacy_md_budget",
                "message": (
                    "Nie można rozliczyć pozostałej puli: historyczne dane "
                    "budżetu MD są niekompletne. Skoryguj stawkę zamówienia "
                    "i ponów decyzję."
                ),
            },
        )
    current_total = Decimal(str(order.md_total))
    new_total = quantize_md(max(Decimal("0"), current_total - remaining))
    total_reduction = current_total - new_total
    overflow = max(Decimal("0"), remaining - total_reduction)
    order.md_total = new_total
    if overflow > 0:
        order.md_manual_adjustment = quantize_md(
            Decimal(str(order.md_manual_adjustment or 0)) - overflow
        )
    if order.md_input_mode == INPUT_MODE_AMOUNT:
        order.md_input_value = quantize_md(new_total * rate_revenue)
    elif order.md_input_mode == INPUT_MODE_MD:
        order.md_input_mode = INPUT_MODE_MD
        order.md_input_value = new_total


async def _restore_offboarded_line(
    db: AsyncSession,
    *,
    case: ClientOrderOffboardingCase,
    group: ClientOrderGroup,
    source: ClientOrder,
    requested_end_date: Optional[date],
    actor_id: Optional[int],
) -> tuple[Optional[date], bool]:
    """Przywróć linię na aktywną obsadę. Zwraca (nowa data końca, czy wskrzeszono kontrakt).

    Symetryczne odwrócenie tego, co ``apply_contract_order_offboarding`` zrobiło
    linii MD w dniu terminacji: tamto ustawiło ``end_date`` na dzień
    zakończenia i status na ``completed``. Odwracamy DOKŁADNIE te dwie rzeczy —
    puli MD nie ruszamy, bo nikt jej nie rozdysponował.

    Data końca NIE jest odtwarzana, tylko podejmowana na nowo: sprawa
    offboardingu snapshotuje pulę, stawki i numer zamówienia, ale nie okres,
    więc oryginalna data końca linii nie istnieje już nigdzie w bazie. Serwer
    nie ma jej skąd wziąć, a zgadnięcie („do końca zamówienia") wpisywałoby do
    przychodu horyzont, którego nikt nie zatwierdził — dlatego przy zamówieniu
    z datą końca pole jest WYMAGANE, a przy bezterminowym puste znaczy
    „bezterminowo".

    Kontrakt wraca razem z linią. Bez tego konsultant zostaje w zakładce
    „Zakończeni" mimo aktywnej linii, a razem z pigułką milczą MRR, rejestr
    umów i skaner wygasania — ta sama klasa awarii, którą naprawiał
    ``sync_contract_to_live_order`` przy przedłużeniach zamówień.
    """

    # Import lokalny — `client_orders` sięga po `client_order_groups` w ciele
    # swoich funkcji, więc import na poziomie modułu domykałby cykl. To jest
    # ta sama konwencja, tylko w drugą stronę.
    from app.api.client_orders import _sync_contract_after_order_extension

    if group.status not in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED):
        raise HTTPException(
            409,
            detail={
                "code": "order_group_not_open",
                "message": (
                    "To zamówienie jest zamknięte — najpierw przywróć samo "
                    "zamówienie, potem konsultanta."
                ),
            },
        )

    today = business_today()
    if group.end_date is not None:
        if requested_end_date is None:
            raise HTTPException(
                422,
                detail=(
                    "Podaj datę, do której współpraca trwa — to zamówienie ma "
                    "datę zakończenia, więc linia nie może być bezterminowa."
                ),
            )
        if requested_end_date > group.end_date:
            raise HTTPException(
                422,
                detail=(
                    "Data zakończenia nie może wykraczać poza zamówienie "
                    f"(kończy się {group.end_date.isoformat()})."
                ),
            )
    if requested_end_date is not None:
        if requested_end_date < today:
            # Data z przeszłości nie przywraca niczego: nocny
            # `_promote_statuses` domknąłby taką linię jeszcze tej nocy
            # (linie ze WSPÓLNĄ pulą mają `md_total IS NULL`, więc wyjątek dla
            # zamówień MD ich nie obejmuje), a decyzja skasowałaby samą siebie.
            raise HTTPException(
                422,
                detail=(
                    "Data zakończenia musi być dzisiejsza albo późniejsza — "
                    "wcześniejsza nie przywraca współpracy."
                ),
            )
        if source.start_date is not None and requested_end_date < source.start_date:
            raise HTTPException(
                422,
                detail="Data zakończenia jest wcześniejsza niż start linii.",
            )

    if not case.uses_shared_md_pool and source.md_total is not None:
        # Pula per linia, wyczerpana: przywrócenie nie miałoby czego kontynuować,
        # a `sync_md_line_status` domknąłby linię z powrotem przy najbliższym
        # przeliczeniu — decyzja wyglądałaby na zapisaną i nie robiła nic.
        current_remaining = await recompute_remaining(db, source)
        if current_remaining <= Decimal("0"):
            raise HTTPException(
                409,
                detail={
                    "code": "md_pool_exhausted",
                    "message": (
                        "Linia nie ma już pozostałej puli MD — najpierw uzupełnij "
                        "budżet zamówienia, potem przywróć konsultanta."
                    ),
                },
            )

    source.end_date = requested_end_date
    source.status = ClientOrderStatus.active

    contract_reopened = False
    contract = source.contract
    if contract is not None:
        contract_reopened = await _sync_contract_after_order_extension(
            db, source, contract, actor_id=actor_id
        )
    return requested_end_date, contract_reopened


# Role uprawnione do CYKLU ŻYCIA zamówienia (usuń / zakończ / przywróć /
# przedłuż). Świadomie SZERSZE niż `_has_md_line_management_role`, który
# rządzi stawkami i zostaje przy admin + Delivery Lead.
#
# Head of Recruitment, TAC, Recruiter, Sourcer i legacy viewer są odcięci od
# całej sekcji Delivery. TCM ma bezpieczny odczyt, więc również nie wykonuje
# tych mutacji. Zostają Admin, przypisany Delivery Lead oraz Finanse.
_ORDER_LIFECYCLE_ROLES = (
    UserRole.admin,
    UserRole.delivery_lead,
    UserRole.finance,
)


#: Zależność tras cyklu życia. Sam test roli — przypisanie do klienta
#: dokłada `_require_order_lifecycle` w ciele handlera, bo zna `client_id`.
OrderLifecycleUser = Annotated[User, Depends(require_roles(*_ORDER_LIFECYCLE_ROLES))]

#: Zależność odczytu surowych zamówień i plików. Granica sekcji jest
#: nakładana na routerze; zawężenie do klienta robi `_require_group_read`.
OrderGroupReader = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.finance,
            UserRole.tac,
        )
    ),
]

# Structured list/history projections are finance-redacted and may be shown to
# TCM. Exports, consultant selectors and PDF files retain ``OrderGroupReader``
# so the read-only role cannot cross the Finance boundary through an opaque
# artefact or a write-oriented helper.
OrderGroupSafeReadUser = Annotated[
    User,
    Depends(
        require_roles(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.talent_community_manager,
            UserRole.finance,
            UserRole.tac,
        )
    ),
]


async def require_consultant_options_reader(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Allow operational Delivery Leads globally and add Finance read only."""

    if current_user.has_role(UserRole.finance) and has_financial_access(current_user):
        return current_user
    return await require_delivery_lead_or_admin(current_user=current_user)


ConsultantOptionsReader = Annotated[User, Depends(require_consultant_options_reader)]


def _has_order_lifecycle_role(user: User) -> bool:
    """Sam test roli dla operacyjnego cyklu życia zamówienia."""
    return user.has_any_role(UserRole.admin, UserRole.delivery_lead) or (
        user.has_role(UserRole.finance)
        and user_has_capability(user, AnalyticsCapability.MANAGE_FINANCE)
    )


async def _require_order_lifecycle(
    db: AsyncSession, user: User, client_id: int
) -> None:
    """Bramka czterech akcji cyklu życia zamówienia.

    Nie reużywa wąskiego guarda przypisań, bo Delivery Lead zarządza operacyjnie
    wszystkimi klientami, a Finance ma te akcje przez ``MANAGE_FINANCE``.
    """
    await _assert_client(db, client_id)
    if not _has_order_lifecycle_role(user):
        raise deny("ta akcja wymaga roli zarządzającej zamówieniami")
    if user.has_role(UserRole.admin) or (
        user.has_role(UserRole.finance)
        and user_has_capability(user, AnalyticsCapability.MANAGE_FINANCE)
    ):
        return
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają dostępu operacyjnego Delivery")


async def _assert_line_finance_write_allowed(
    db: AsyncSession,
    user: User,
    client_id: int,
    supplied: set[str],
) -> None:
    """Kwoty grupy i linii pisze admin albo przypisany Delivery Lead."""
    forbidden = sorted(supplied & _GROUP_FINANCE_FIELDS)
    if forbidden and not await _has_md_line_management_access(db, user, client_id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "finance_fields_forbidden", "fields": forbidden},
        )


async def _can_see_finance(db: AsyncSession, user: User, client_id: int) -> bool:
    """Stawki linii MD widzi ten, kto może je ustawiać, oraz role z VIEW_FINANCE.

    TAC zostaje przy redakcji: jest w zespole klienta i widzi konsultantów oraz
    zużycie MD, ale nie prowadzi obsady zamówienia, więc stawki go nie dotyczą.
    """
    return user_has_capability(
        user, AnalyticsCapability.VIEW_FINANCE
    ) or await _has_md_line_management_access(db, user, client_id)


def _initial_group_status(start_date: date) -> str:
    """Status stemplowany przy zakładaniu grupy — tym samym dniem, którym
    ocenia ją później materializator.

    `business_today()`, nie `date.today()`: promocję `scheduled → active` robi
    `order_group_lifecycle.materialize_scheduled_order_groups`, a ten liczy
    granicę DNIEM BIZNESOWYM (Europe/Warsaw). Kontener chodzi w UTC, więc
    między 22:00 UTC a północą (latem) obie funkcje datowały się różnymi
    dobami: zamówienie zaczynające się „jutro" wg UTC — czyli DZIŚ wg firmy —
    dostawało w odpowiedzi POST-a `scheduled`, po czym pierwszy odczyt listy
    natychmiast przestawiał je na `active`. Ten sam rozjazd dwóch zegarów
    w jednym module, który materializator ma usuwać.
    """
    return (
        GROUP_STATUS_SCHEDULED if start_date > business_today() else GROUP_STATUS_ACTIVE
    )


def _group_family_root_id(
    group: ClientOrderGroup, by_id: dict[int, ClientOrderGroup]
) -> int:
    current = group
    seen = {group.id}
    while current.predecessor_group_id in by_id:
        parent = by_id[current.predecessor_group_id]  # type: ignore[index]
        if parent.id in seen:
            break
        seen.add(parent.id)
        current = parent
    return current.id


async def _sync_group_pdf_documents(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    payload: bytes,
    user: User,
) -> list[str]:
    """Upsert one automatic ``ContractDocument`` per assigned contract.

    Existing linked documents are included even after a consultant was removed
    from the group, so replacing the master PDF updates the historical copy as
    required. Manual documents have ``source_order_group_id IS NULL`` and are
    never touched.
    """

    current_contract_ids = set(
        (
            await db.execute(
                select(ClientOrder.contract_id).where(
                    ClientOrder.order_group_id == group.id
                )
            )
        ).scalars()
    )
    linked = list(
        (
            await db.execute(
                select(ContractDocument).where(
                    ContractDocument.source_order_group_id == group.id
                )
            )
        ).scalars()
    )
    by_contract = {document.contract_id: document for document in linked}
    target_contract_ids = current_contract_ids | set(by_contract)
    superseded_paths: list[str] = []

    for contract_id in sorted(target_contract_ids):
        rel_path, size = storage_service.save_contract_document(
            contract_id,
            f"{group.order_number}.pdf",
            io.BytesIO(payload),
        )
        document = by_contract.get(contract_id)
        if document is None:
            document = ContractDocument(
                contract_id=contract_id,
                source_order_group_id=group.id,
                doc_type=ContractDocumentType.order,
                filename=group.order_number,
                file_path=rel_path,
                content_type="application/pdf",
                size_bytes=size,
                uploaded_by=user.id,
            )
            db.add(document)
        else:
            if document.file_path and document.file_path != rel_path:
                superseded_paths.append(document.file_path)
            document.filename = group.order_number
            document.file_path = rel_path
            document.content_type = "application/pdf"
            document.size_bytes = size
            document.doc_type = ContractDocumentType.order
            document.uploaded_by = user.id
    await db.flush()
    return superseded_paths


async def _sync_group_pdf_for_new_line(
    db: AsyncSession, *, group: ClientOrderGroup, user: User
) -> list[str]:
    if not group.file_path:
        return []
    try:
        payload = storage_service.get_client_order_group_po_path(
            group.file_path
        ).read_bytes()
    except FileNotFoundError as exc:
        raise HTTPException(410, detail="Plik PDF zamówienia nie istnieje") from exc
    return await _sync_group_pdf_documents(db, group=group, payload=payload, user=user)


async def _load_group(
    db: AsyncSession, client_id: int, group_id: int
) -> ClientOrderGroup:
    group = await db.scalar(
        select(ClientOrderGroup).where(
            ClientOrderGroup.id == group_id,
            ClientOrderGroup.client_id == client_id,
        )
    )
    if group is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje")
    # 0251 is schema-only/NOT VALID. Empty generic rows carrying the phantom
    # 0246 pool become constraint-valid on their first ordinary write; rows
    # with consultant data fail closed and are never rewritten here.
    await normalize_empty_generic_explicit_md_group(db, group)
    return group


def _line_to_read(
    order: ClientOrder,
    *,
    with_finance: bool,
    invoiced: Optional[Decimal] = None,
    unsettled: Optional[Decimal] = None,
    missing_month: Optional[str] = None,
    offboarding_case: Optional[ClientOrderOffboardingCase] = None,
) -> OrderLineRead:
    contract = order.contract
    predecessor_name: Optional[str] = None
    if order.predecessor is not None:
        predecessor_name = consultant_display_name(order.predecessor)

    # Kwota widziana przez rolę bez VIEW_FINANCE musi zniknąć, ale liczba MD
    # zostaje — pasek zużycia jest informacją operacyjną, nie finansową.
    input_value: Optional[Decimal] = order.md_input_value
    if not with_finance and order.md_input_mode == INPUT_MODE_AMOUNT:
        input_value = None

    return OrderLineRead(
        id=order.id,
        group_id=order.order_group_id,
        contract_id=order.contract_id,
        candidate_id=contract.candidate_id if contract else None,
        consultant_name=consultant_display_name(order),
        job_id=order.job_id,
        job_title=None,
        status=order.status.value,
        is_active=order.status == ClientOrderStatus.active,
        start_date=order.start_date,
        end_date=order.end_date,
        source_rate_cost=(
            order.md_rate_cost
            if (order.rate_candidate_currency or order.currency or "PLN").upper()
            == "PLN"
            else convert_order_rate(
                order.rate_candidate,
                order.rate_unit or RateUnit.daily,
                RateUnit.daily,
                order.billing_hours_per_month or 160,
            )
        )
        if with_finance
        else None,
        source_rate_revenue=(
            order.md_rate_revenue
            if (order.rate_client_currency or order.currency or "PLN").upper() == "PLN"
            else convert_order_rate(
                order.rate_client,
                order.rate_unit or RateUnit.daily,
                RateUnit.daily,
                order.billing_hours_per_month or 160,
            )
        )
        if with_finance
        else None,
        rate_candidate_currency=(
            order.rate_candidate_currency or order.currency or "PLN"
        ).upper()
        if with_finance
        else None,
        rate_client_currency=(
            order.rate_client_currency or order.currency or "PLN"
        ).upper()
        if with_finance
        else None,
        rate_cost=order.md_rate_cost if with_finance else None,
        rate_revenue=order.md_rate_revenue if with_finance else None,
        input_value=input_value,
        input_mode=order.md_input_mode,
        md_total=order.md_total,
        md_remaining=order.md_remaining,
        md_manual_adjustment=order.md_manual_adjustment,
        predecessor_order_id=order.predecessor_order_id,
        predecessor_consultant_name=predecessor_name,
        invoiced_total=invoiced,
        unsettled_total=unsettled,
        missing_consumption_month=missing_month,
        offboarding_case=(
            _offboarding_case_to_read(offboarding_case, with_finance=with_finance)
            if offboarding_case is not None
            else None
        ),
    )


def _offboarding_case_to_read(
    case: ClientOrderOffboardingCase, *, with_finance: bool
) -> OrderOffboardingCaseRead:
    """Serialize one workflow case without bypassing finance redaction."""

    return OrderOffboardingCaseRead(
        id=case.id,
        contract_id=case.contract_id,
        order_id=case.order_id,
        order_group_id=case.order_group_id,
        client_id=case.client_id,
        effective_date=case.effective_date,
        status=case.status,
        version=case.version,
        uses_shared_md_pool=case.uses_shared_md_pool,
        remaining_md_snapshot=case.remaining_md_snapshot,
        rate_cost_snapshot=case.rate_cost_snapshot if with_finance else None,
        rate_revenue_snapshot=(case.rate_revenue_snapshot if with_finance else None),
        currency_snapshot=case.currency_snapshot if with_finance else None,
        order_number_snapshot=case.order_number_snapshot,
        resolution=case.resolution,
        target_order_id=case.target_order_id,
        rate_basis=case.rate_basis,
        resolution_payload=case.resolution_payload if with_finance else None,
        resolved_at=case.resolved_at,
        resolved_by_user_id=case.resolved_by_user_id,
        created_by_user_id=case.created_by_user_id,
        created_at=case.created_at,
        updated_at=case.updated_at,
    )


async def _group_to_read(
    db: AsyncSession,
    group: ClientOrderGroup,
    *,
    with_finance: bool,
    precomputed_md_budget_used: Optional[Decimal] = None,
) -> OrderGroupRead:
    lines = await lines_for_group(db, group.id)
    uses_shared_md_budget = uses_shared_md_pool(group)
    offboarding_by_order: dict[int, ClientOrderOffboardingCase] = {}
    if lines:
        case_rows = list(
            (
                await db.scalars(
                    select(ClientOrderOffboardingCase)
                    .where(
                        ClientOrderOffboardingCase.order_id.in_(
                            [line.id for line in lines]
                        )
                    )
                    .order_by(
                        ClientOrderOffboardingCase.effective_date.desc(),
                        ClientOrderOffboardingCase.id.desc(),
                    )
                )
            ).all()
        )
        # Nierozwiązana decyzja ma pierwszeństwo przed nowszym historycznym
        # epizodem; normalnie unikalność odcinka czasu daje jedną sprawę, ale
        # reaktywacja kontraktu może utworzyć kolejny epizod zakończenia.
        for case in case_rows:
            previous = offboarding_by_order.get(case.order_id)
            if previous is None or (
                previous.status != OFFBOARDING_STATUS_PENDING
                and case.status == OFFBOARDING_STATUS_PENDING
            ):
                offboarding_by_order[case.order_id] = case
    job_titles: dict[int, str] = {}
    job_ids = [line.job_id for line in lines if line.job_id]
    if job_ids:
        rows = await db.execute(
            select(Job.id, Job.title).where(Job.id.in_(set(job_ids)))
        )
        job_titles = {jid: title for jid, title in rows}

    invoiced: dict[int, Decimal] = {}
    unsettled: dict[int, Decimal] = {}
    missing_month: dict[int, Optional[str]] = {}
    if group.is_cost_based and lines:
        # JEDNO zapytanie na całe zamówienie, nie jedno na linię — karta
        # zamówienia pokazuje wszystkie linie naraz, więc N+1 tutaj skalowałby
        # się z obsadą.
        line_ids = [line.id for line in lines]
        rows = await db.execute(
            select(
                ClientOrderInvoiceConsumption.order_id,
                func.coalesce(
                    func.sum(ClientOrderInvoiceConsumption.invoice_amount), 0
                ),
                func.coalesce(
                    func.sum(ClientOrderInvoiceConsumption.unsettled_amount), 0
                ),
            )
            .where(ClientOrderInvoiceConsumption.order_id.in_(line_ids))
            .group_by(ClientOrderInvoiceConsumption.order_id)
        )
        for order_id, total, missing in rows:
            invoiced[order_id] = quantize_money(total or 0)
            unsettled[order_id] = quantize_money(missing or 0)

        # „Brak zejścia za {miesiąc}" — komunikat ma sens dopiero wtedy, gdy
        # JAKIŚ import za ten miesiąc się odbył. Bez tego warunku każde świeżo
        # założone zamówienie krzyczałoby o braku zejścia za miesiąc, w którym
        # jeszcze nikt niczego nie raportował.
        latest_import_month = await db.scalar(
            select(func.max(MdConsumptionImport.period_month))
        )
        if latest_import_month:
            settled_rows = await db.execute(
                select(ClientOrderInvoiceConsumption.order_id).where(
                    ClientOrderInvoiceConsumption.order_id.in_(line_ids),
                    ClientOrderInvoiceConsumption.period_month == latest_import_month,
                )
            )
            with_month = {oid for (oid,) in settled_rows}
            for line in lines:
                if line.id not in with_month:
                    missing_month[line.id] = latest_import_month

    # Kwoty grupy i sumy zafakturowane są po TEJ SAMEJ stronie linii co stawki
    # linii: `md_total` jest jawne z założenia (liczba MD jest operacyjna), więc
    # rola bez VIEW_FINANCE, widząc kwotę zamówienia obok liczby MD, odtwarza
    # dzieleniem dokładnie tę stawkę przychodową, którą serwer właśnie
    # zredagował. Siostrzany moduł jednoosobowy redaguje bezpośredni
    # odpowiednik (`ClientOrder.total_value`, `_ORDER_FINANCE_FIELDS`) dla tych
    # samych ról — tu było przeoczenie, nie odrębna decyzja.
    reads: list[OrderLineRead] = []
    for line in lines:
        item = _line_to_read(
            line,
            with_finance=with_finance,
            invoiced=(
                invoiced.get(line.id) if group.is_cost_based and with_finance else None
            ),
            unsettled=(
                unsettled.get(line.id) if group.is_cost_based and with_finance else None
            ),
            missing_month=missing_month.get(line.id),
            offboarding_case=offboarding_by_order.get(line.id),
        )
        if item.job_id:
            item.job_title = job_titles.get(item.job_id)
        reads.append(item)
    reads.sort(
        key=lambda item: (
            normalize_person_name_part(item.consultant_name),
            item.id,
        )
    )

    # Licznik na przycisku MUSI przejść przez ten sam filtr co lista wpisów.
    # `COUNT(*)` dawał „Historia zamówienia (6 wpisów)" nad listą dwóch
    # pozycji, czyli komunikat czytający się jak utrata danych. Stąd odczyt
    # dwóch kolumn zamiast agregatu — predykat jest w Pythonie, bo zależy od
    # zawartości `payload`, a jedna definicja użyta w obu miejscach jest warta
    # więcej niż zaoszczędzone wiersze (dziennik jednej grupy to kilkadziesiąt
    # pozycji, nie tysiące).
    event_rows = await db.execute(
        select(ClientOrderGroupEvent.event_type, ClientOrderGroupEvent.payload).where(
            ClientOrderGroupEvent.group_id == group.id
        )
    )
    event_count = sum(
        1
        for event_type, payload in event_rows
        if not _is_technical_event(event_type, payload)
    )

    budget_used: Optional[Decimal] = None
    if group.is_cost_based and group.budget_amount is not None:
        pool = quantize_money(group.budget_amount) + quantize_money(
            group.budget_manual_adjustment or 0
        )
        remaining = quantize_money(group.budget_remaining or 0)
        budget_used = quantize_money(max(Decimal("0"), pool - remaining))

    md_budget_used: Optional[Decimal] = None
    if uses_shared_md_budget:
        md_budget_used = (
            quantize_md(precomputed_md_budget_used)
            if precomputed_md_budget_used is not None
            else await shared_md_used_total(db, group.id)
        )

    return OrderGroupRead(
        id=group.id,
        client_id=group.client_id,
        order_number=group.order_number,
        start_date=group.start_date,
        end_date=group.end_date,
        notes=group.notes,
        created_at=group.created_at,
        status=group.status,
        status_label=GROUP_STATUS_LABELS.get(group.status, group.status),
        md_budget_mode=group.md_budget_mode,
        md_budget_mode_locked=(
            group.md_budget_mode is None
            or group.status != "draft"
            or group.md_budget_mode_locked
        ),
        closure_date=group.closure_date,
        closure_reason=group.closure_reason,
        order_type=group.order_type,
        is_cost_based=group.is_cost_based,
        budget_amount=group.budget_amount if with_finance else None,
        budget_used=budget_used if with_finance else None,
        budget_remaining=group.budget_remaining if with_finance else None,
        budget_manual_adjustment=(
            group.budget_manual_adjustment
            if group.is_cost_based and with_finance
            else None
        ),
        is_md_budget_based=uses_shared_md_budget,
        md_budget_total=(group.md_budget_total if uses_shared_md_budget else None),
        md_budget_used=md_budget_used,
        md_budget_remaining=(
            group.md_budget_remaining if uses_shared_md_budget else None
        ),
        md_budget_manual_adjustment=(
            group.md_budget_manual_adjustment if uses_shared_md_budget else None
        ),
        predecessor_group_id=group.predecessor_group_id,
        filename=group.filename,
        has_file=group.file_path is not None,
        content_type=group.content_type,
        size_bytes=group.size_bytes,
        file_uploaded_at=group.file_uploaded_at,
        can_add_consultant=group.status
        in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED, "draft"),
        lines=reads,
        active_consultants=sum(1 for r in reads if r.is_active),
        event_count=event_count,
    )


async def _normalize_empty_explicit_md_group(
    db: AsyncSession, group: ClientOrderGroup
) -> bool:
    """API adapter for the canonical, fail-closed write-time self-heal."""

    return await normalize_empty_generic_explicit_md_group(db, group)


async def _resolve_contract(
    db: AsyncSession, client_id: int, contract_id: int
) -> Contract:
    contract = await db.scalar(
        select(Contract)
        .options(selectinload(Contract.candidate))
        .where(Contract.id == contract_id, Contract.client_id == client_id)
    )
    if contract is None:
        raise HTTPException(
            400, detail="Wybrany konsultant nie ma kontraktu u tego klienta"
        )
    return contract


async def _contract_for_candidate(
    db: AsyncSession,
    *,
    client_id: int,
    candidate_id: int,
    start_date: date,
) -> tuple[Contract, Optional[Candidate], bool]:
    """Kontrakt u tego klienta dla osoby z bazy Nexus — istniejący albo nowy.

    Zwraca `(kontrakt, kandydat, czy_utworzono)`. Kandydat wraca OSOBNO, bo dla
    świeżo utworzonego kontraktu relacja ``contract.candidate`` nie jest
    załadowana i sięgnięcie po nią odpaliłoby leniwe doczytanie — w async
    SQLAlchemy kończy się to ``MissingGreenlet``, czyli 500 bez nagłówków CORS
    (w przeglądarce „Network Error" bez żadnej wskazówki).

    Istniejący kontrakt jest REUŻYWANY, nawet gdy operator przyszedł ścieżką
    „z bazy Nexus": drugi równoległy kontrakt u tego samego klienta rozdwoiłby
    prawdę o tym, kto tam pracuje — a to jest dokładnie ta rzecz, której cały
    moduł pilnuje.
    """
    candidate = await db.scalar(select(Candidate).where(Candidate.id == candidate_id))
    if candidate is None:
        raise HTTPException(400, detail="Nie znaleziono osoby o tym identyfikatorze")

    existing = await db.scalar(
        select(Contract)
        .where(
            Contract.candidate_id == candidate_id,
            Contract.client_id == client_id,
            Contract.status.in_(CLIENT_CONTRACT_STATUSES),
        )
        .order_by(Contract.start_date.desc().nullslast(), Contract.id.desc())
    )
    if existing is not None:
        # Zwracamy kandydata pobranego wyżej, a NIE `existing.candidate`: to ta
        # sama osoba (WHERE filtruje po jej id), więc nie ma czego doczytywać.
        # Dzięki temu nie trzeba tu `selectinload` — a bez niego sięgnięcie po
        # relację byłoby leniwym doczytaniem, czyli `MissingGreenlet` w async.
        return existing, candidate, False

    contract = Contract(
        candidate_id=candidate_id,
        client_id=client_id,
        # `draft`, nie `active`: aktywacja kontraktu ma własny cykl życia
        # (``contract_lifecycle.activate_contract``), który waliduje komplet
        # danych i dowód podpisu. Obsada zamówienia nie może go obchodzić
        # bokiem — inaczej osoba wchodziłaby do MRR i alertów wygasania na
        # podstawie formularza, który o umowie nie pyta.
        status=ContractStatus.draft,
        start_date=start_date,
        # BEZ `end_date`. Koniec ZAMÓWIENIA i koniec UMOWY to dwa różne fakty:
        # zamówienie wygasa co pół roku, a umowa B2B jest bezterminowa aż do
        # rozstania z konsultantem. Przepisanie tu daty z linii dawało umowie
        # datę końca, której nikt nie zadeklarował — nocny `_promote_statuses`
        # przestawiał ją na „Kończąca się", a potem „Zakończona", i konsultant
        # znikał z rejestru mimo trwającego zamówienia. Datę zakończenia umowy
        # ustawia wyłącznie człowiek (rejestr umów albo `/terminate`).
    )
    db.add(contract)
    await db.flush()
    return contract, candidate, True


async def _resolve_line_person(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    payload: OrderLineCreate,
) -> tuple[Contract, Optional[Candidate], bool]:
    """Kogo dotyczy linia — z kontraktu u klienta albo z bazy Nexus."""
    if payload.contract_id is not None:
        contract = await _resolve_contract(db, group.client_id, payload.contract_id)
        return contract, contract.candidate, False
    # Schemat gwarantuje, że dokładnie jedno z pól jest ustawione.
    #
    # Data ROZPOCZĘCIA szkicu kontraktu jest lustrem daty linii, bo tylko tyle
    # wiadomo: formularz obsady nie pyta o okres umowy. Data ZAKOŃCZENIA
    # świadomie NIE jest kopiowana — patrz `_contract_for_candidate`. Kto
    # będzie ten kontrakt aktywował, i tak musi datę startu potwierdzić: to nie
    # jest data przepisana z umowy, tylko z zamówienia, pod które osoba została
    # dopisana.
    return await _contract_for_candidate(
        db,
        client_id=group.client_id,
        candidate_id=payload.candidate_id,  # type: ignore[arg-type]
        start_date=payload.start_date,
    )


async def _build_line(
    db: AsyncSession,
    *,
    group: ClientOrderGroup,
    payload: OrderLineCreate,
    user: User,
) -> tuple[ClientOrder, str, bool]:
    contract, candidate, contract_created = await _resolve_line_person(
        db, group=group, payload=payload
    )
    # Osoba wchodzi na linię grupy — pusty szkic-zaślepka po hooku zatrudnienia
    # przestaje być „do uzupełnienia" i staje się DRUGIM zapisem tej samej
    # współpracy. Zostawiony na kontrakcie sprawiał, że wypowiedzenie z karty
    # okresowej domykało również tę linię (patrz
    # `order_engagement_separation`).
    #
    # Ślad w `activities` jest OBOWIĄZKOWY i ma ten sam kształt co wpis migracji
    # 0261: kasowanie wiersza, którego nikt nie widzi w historii, jest dla
    # operatora nieodróżnialne od danych, które zniknęły same.
    for removed_order_id in await absorb_auto_draft_shells(db, contract.id):
        db.add(
            Activity(
                entity_type="client_order",
                entity_id=removed_order_id,
                action="order_deleted",
                user_id=user.id,
                details={
                    "contract_id": contract.id,
                    "client_id": group.client_id,
                    "order_group_id": group.id,
                    "reason": "absorbed_auto_draft_shell",
                },
            )
        )
    if payload.job_id is not None:
        owns_job = await db.scalar(
            select(Job.id).where(
                Job.id == payload.job_id, Job.client_id == group.client_id
            )
        )
        if owns_job is None:
            raise HTTPException(400, detail="Rekrutacja nie należy do tego klienta")

    # Zamówienie KOSZTOWE ma jedną, wspólną pulę na grupie — linia nie niesie
    # własnego budżetu MD. Wymuszenie budżetu tutaj zmusiłoby operatora do
    # wymyślenia liczby, której nikt nigdy nie rozliczy, a CHECK spójności
    # w bazie i tak dopuszcza komplet NULL-i.
    md_total: Optional[Decimal] = None
    if group.is_cost_based or uses_shared_md_pool(group):
        if payload.input_mode is not None or payload.input_value is not None:
            raise HTTPException(
                422,
                detail=(
                    "To zamówienie ma wspólny budżet całej grupy — nie podawaj "
                    "budżetu przy konsultancie"
                ),
            )
    else:
        if payload.input_mode is None or payload.input_value is None:
            raise HTTPException(
                422, detail="Podaj budżet konsultanta (liczbę MD albo kwotę)"
            )
        try:
            md_total = compute_md_total(
                input_mode=payload.input_mode,
                input_value=payload.input_value,
                rate_revenue=payload.rate_revenue,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    who = (
        f"{candidate.name or ''} {candidate.lastname or ''}".strip()
        if candidate
        else ""
    )
    now = datetime.now(timezone.utc)
    line_status = (
        ClientOrderStatus.draft
        if group.status in (GROUP_STATUS_SCHEDULED, "draft")
        else ClientOrderStatus.active
    )
    line = ClientOrder(
        client_id=group.client_id,
        contract_id=contract.id,
        job_id=payload.job_id,
        order_group_id=group.id,
        order_type=group.order_type,
        title=f"Zamówienie {group.order_number} — {who or 'konsultant'}"[:255],
        status=line_status,
        start_date=payload.start_date,
        end_date=payload.end_date or group.end_date,
        filled_at=now if line_status == ClientOrderStatus.active else None,
        md_rate_cost=await _canonical_currency_rate(
            db,
            payload.rate_cost,
            payload.rate_candidate_currency or "PLN",
            payload.start_date,
        ),
        md_rate_revenue=await _canonical_currency_rate(
            db,
            payload.rate_revenue,
            payload.rate_client_currency or "PLN",
            payload.start_date,
        ),
        rate_candidate=payload.rate_cost,
        rate_client=payload.rate_revenue,
        rate_unit=RateUnit.daily,
        billing_hours_per_month=160,
        currency=payload.rate_client_currency or "PLN",
        rate_client_currency=payload.rate_client_currency or "PLN",
        rate_candidate_currency=payload.rate_candidate_currency or "PLN",
        md_input_mode=payload.input_mode,
        md_input_value=payload.input_value,
        md_total=md_total,
        md_remaining=md_total,
        md_manual_adjustment=Decimal("0"),
        created_by_user_id=user.id,
    )
    db.add(line)
    # Zwracamy nazwisko RAZEM z linią, zamiast odczytywać je później przez
    # `line.contract.candidate`: świeżo skonstruowany obiekt nie ma załadowanej
    # relacji, więc sięgnięcie po nią odpaliłoby leniwe doczytanie — w async
    # SQLAlchemy kończy się to `MissingGreenlet`, czyli 500 bez CORS
    # (w przeglądarce „Network Error" bez żadnej wskazówki).
    return line, who or "konsultant", contract_created


async def _sync_contract_after_live_group_line(
    db: AsyncSession, line: ClientOrder, *, actor_id: Optional[int]
) -> bool:
    """Apply the Contract↔live-order invariant to a freshly active group line."""

    if line.status in (ClientOrderStatus.draft, ClientOrderStatus.cancelled):
        return False
    contract = await db.get(Contract, line.contract_id)
    if contract is None:
        return False
    return await sync_contract_to_live_order(
        db,
        contract,
        order_start=line.start_date,
        order_end=line.end_date,
        actor_id=actor_id,
        today=business_today(),
    )


def _describe_line(
    order: ClientOrder,
    who: str,
    *,
    group: ClientOrderGroup,
    contract_created: bool = False,
) -> str:
    # Fakt założenia kontraktu ląduje w opisie zdarzenia, a nie tylko w polach
    # linii: historia zamówienia jest jedynym miejscem, w którym widać, że ta
    # osoba weszła spoza rekrutacji u tego klienta i ma u niego świeży szkic
    # umowy do domknięcia.
    suffix = (
        " (osoba z bazy Nexus — założono szkic kontraktu)" if contract_created else ""
    )
    if order.md_total is None:
        if uses_shared_md_pool(group):
            return f"{who} — konsultant na zamówieniu ze wspólną pulą MD{suffix}"
        # Linia zamówienia kosztowego — budżetu MD nie ma, więc wypisywanie
        # „budżet — MD" mówiłoby o polu, którego ta linia nigdy nie miała.
        return f"{who} — konsultant na zamówieniu kosztowym{suffix}"
    return (
        f"{who} — stawka kosztowa {format_md(order.md_rate_cost)} zł/MD, "
        f"przychodowa {format_md(order.md_rate_revenue)} zł/MD, "
        f"budżet {format_md(order.md_total)} MD{suffix}"
    )


# ── Odczyt ──────────────────────────────────────────────────────────────────


@router.get("/{client_id}/order-groups", response_model=OrderGroupListResponse)
async def list_order_groups(
    client_id: int,
    user: OrderGroupSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Zamówienia klienta wraz z liniami konsultantów.

    Klient spoza listy dostaje PUSTĄ listę, nie 403 — front pyta o ten zasób
    dopiero po sprawdzeniu flagi, a odmowa renderowałaby się jako awaria tam,
    gdzie faktycznie po prostu nie ma czego pokazać.
    """
    await _require_safe_group_read(db, user, client_id)

    # Scanner materializuje przejścia codziennie, ale odczyt jest dodatkową
    # idempotentną bramą: zamówienie zaczynające się dziś ma stać się bieżące
    # przy pierwszym wejściu użytkownika, nawet jeśli pętla dobowa jeszcze nie
    # zdążyła wykonać iteracji.
    if await materialize_scheduled_order_groups(db, client_id=client_id):
        await db.commit()

    groups_query = select(ClientOrderGroup).where(
        ClientOrderGroup.client_id == client_id
    )
    if not is_multi_consultant_client(client_id):
        # Dla nowych klientów pokazujemy wyłącznie grupy utworzone przez jawny
        # selektor. Ewentualny stary/sierocy rekord bez typu nie staje się
        # widoczny tylko dlatego, że wdrożyliśmy mechanizm globalny.
        groups_query = groups_query.where(ClientOrderGroup.order_type.is_not(None))
    result = await db.execute(
        groups_query.order_by(
            ClientOrderGroup.created_at.desc(), ClientOrderGroup.id.desc()
        )
    )
    with_finance = await _can_see_finance(db, user, client_id)
    models = list(result.scalars())
    shared_md_used_by_group = await shared_md_used_totals(
        db, (group.id for group in models if uses_shared_md_pool(group))
    )
    reads_by_id = {
        group.id: await _group_to_read(
            db,
            group,
            with_finance=with_finance,
            precomputed_md_budget_used=(
                shared_md_used_by_group[group.id]
                if uses_shared_md_pool(group)
                else None
            ),
        )
        for group in models
    }

    # Każda rodzina = bieżąca karta + chronologiczna kolejka kontynuacji.
    # Scheduled nigdy nie trafia jako równorzędna karta głównej listy, jeśli
    # istnieje jej aktywny poprzednik.
    by_id = {group.id: group for group in models}
    families: dict[int, list[ClientOrderGroup]] = {}
    for group in models:
        root_id = _group_family_root_id(group, by_id)
        families.setdefault(root_id, []).append(group)

    hidden_future_ids: set[int] = set()
    for family in families.values():
        future = sorted(
            (g for g in family if g.status == GROUP_STATUS_SCHEDULED),
            key=lambda g: (g.start_date, g.id),
        )
        if not future:
            continue
        active = sorted(
            (g for g in family if g.status == GROUP_STATUS_ACTIVE),
            key=lambda g: (g.start_date, g.id),
            reverse=True,
        )
        if active:
            parent = active[0]
            reads_by_id[parent.id].future_orders = [reads_by_id[g.id] for g in future]
            hidden_future_ids.update(g.id for g in future)
        else:
            # Rodzina utworzona wyłącznie na przyszłość: najbliższy wpis jest
            # kartą-kotwicą, kolejne pozostają zagnieżdżone pod nim.
            anchor, *rest = future
            reads_by_id[anchor.id].future_orders = [reads_by_id[g.id] for g in rest]
            hidden_future_ids.update(g.id for g in rest)

    groups = [
        reads_by_id[group.id] for group in models if group.id not in hidden_future_ids
    ]
    if _is_read_only_tcm(user):
        for group in groups:
            _redact_group_document_metadata(group)
    draft_orders = await _list_draft_orders(db, client_id, with_finance=with_finance)
    return OrderGroupListResponse(
        groups=groups,
        total_groups=len(models),
        total_consultants=sum(read.active_consultants for read in reads_by_id.values()),
        suggested_order_type=await suggested_order_type(db, client_id),
        draft_orders=draft_orders,
        total_draft_orders=len(draft_orders),
    )


# Zakładka „Draft (do uzupełnienia)" pokazuje WYŁĄCZNIE szkice utworzone od
# dnia wdrożenia. Decyzja ticketu (2026-08-24, req 7): istniejące szkice
# BIK/BNP — nawet niekompletne — nie są retroaktywnie wciągane do nowej
# zakładki; pozostają tam, gdzie były (czyli w alertach DL), do osobnej,
# zaakceptowanej migracji. Stała w kodzie, nie w ENV: to data wdrożenia,
# fakt historyczny, a nie pokrętło operacyjne.
_DRAFT_ORDERS_TAB_SINCE = datetime(2026, 8, 24, tzinfo=timezone.utc)


async def _list_draft_orders(
    db: AsyncSession, client_id: int, *, with_finance: bool
) -> list[OrderDraftRead]:
    """Samodzielne szkice zamówień klienta MD — treść zakładki Draft.

    Tylko klienci wielo-konsultantowi BEZ zamówień kosztowych: u kosztowych
    (Polkomtel) hook zatrudnienia nie tworzy szkiców (`should_auto_create_order`)
    i zakładka Draft się nie renderuje — pusta lista utrzymuje ten kontrakt
    także na poziomie API. Szkic przypięty już do grupy (linia draft w grupie
    ``scheduled``) ma swoją kartę w rejestrze grup i tu się nie liczy.
    """
    if hides_standard_drafts_from_order_group_registry(client_id):
        return []
    rows = (
        (
            await db.execute(
                select(ClientOrder)
                .options(
                    selectinload(ClientOrder.contract).selectinload(Contract.candidate),
                    # Efektywna stawka kosztowa czyta harmonogram — bez
                    # eager-loadu byłby to MissingGreenlet (500 bez CORS).
                    selectinload(ClientOrder.contract).selectinload(
                        Contract.candidate_rate_schedule
                    ),
                )
                .where(
                    ClientOrder.client_id == client_id,
                    ClientOrder.status == ClientOrderStatus.draft,
                    ClientOrder.order_group_id.is_(None),
                    ClientOrder.created_at >= _DRAFT_ORDERS_TAB_SINCE,
                )
                .order_by(ClientOrder.created_at.desc(), ClientOrder.id.desc())
            )
        )
        .scalars()
        .all()
    )
    today = business_today()
    reads: list[OrderDraftRead] = []
    for order in rows:
        contract = order.contract
        rate_cost = (
            contract.effective_candidate_rate(today) if contract is not None else None
        )
        reads.append(
            OrderDraftRead(
                id=order.id,
                contract_id=order.contract_id,
                consultant_name=consultant_display_name(order),
                title=order.title or "",
                order_type=order.order_type,
                start_date=order.start_date,
                end_date=order.end_date,
                # Stawki jak w liniach: zerowane dla ról bez dostępu do kwot.
                # Liczba MD jest operacyjna i zostaje widoczna (kontrakt md_total
                # w OrderLineRead).
                rate_cost=rate_cost if with_finance else None,
                rate_revenue=order.rate_client if with_finance else None,
                md_quantity=order.md_total,
                created_at=order.created_at,
            )
        )
    return reads


def assert_group_is_reopenable(status: str) -> None:
    """Przywrócić da się WYŁĄCZNIE zamówienie zakończone ręcznie.

    Bramka jest WYCZERPUJĄCA i musi taka zostać. Poprzednia wersja odmawiała
    tylko dla ``active`` i ``exhausted``, bo pisano ją w świecie trzech
    statusów, gdzie „nic z tych dwóch" znaczyło „completed". Po dołożeniu
    ``scheduled`` zamówienie przyszłe przechodziło obie bramki i dostawało
    ``active`` PRZED datą startu, a jego linie zostawały w ``draft`` (reopen
    ich nie rusza) — czyli „bieżące" zamówienie z zerem aktywnych konsultantów.
    Materializer już by tego nie naprawił: kolejkę bierze wyłącznie z wierszy
    ``scheduled``, więc ani ta grupa nie wróciłaby do kolejki, ani jej
    poprzednik nie zostałby domknięty — w rodzinie zostałyby dwa aktywne
    zamówienia naraz.

    Wyniesione z handlera, żeby dołożenie kolejnego statusu dało się sprawdzić
    bez stawiania klienta, grupy i sesji: to jest miejsce, w którym nowy status
    cicho wpada w gałąź „zakończone".
    """

    if status == GROUP_STATUS_ACTIVE:
        raise HTTPException(409, detail="To zamówienie jest już aktywne")
    if status == GROUP_STATUS_SCHEDULED:
        # Zamówienia, które jeszcze nie ruszyło, się nie przywraca — się je
        # edytuje albo usuwa.
        raise HTTPException(
            409,
            detail=(
                "To zamówienie jeszcze nie ruszyło — nie ma czego przywracać. "
                "Zmień datę rozpoczęcia albo usuń zamówienie."
            ),
        )
    if status == GROUP_STATUS_EXHAUSTED:
        raise HTTPException(
            409,
            detail=(
                "Zamówienie jest wyczerpane, nie zakończone. Skoryguj budżet "
                "zamówienia albo załóż nowe."
            ),
        )
    if status != GROUP_STATUS_COMPLETED:
        # Nowy status dorzucony do modelu bez zajrzenia tutaj ma zostać
        # odrzucony, a nie potraktowany jak „zakończone".
        raise HTTPException(
            409,
            detail=(
                "Zamówienia w stanie "
                f"„{GROUP_STATUS_LABELS.get(status, status)}” nie da się "
                "przywrócić."
            ),
        )


@router.post("/{client_id}/order-groups/export")
async def export_order_groups(
    client_id: int,
    payload: OrderGroupExportRequest,
    user: OrderGroupReader,
    db: AsyncSession = Depends(get_db),
):
    """Export the exact filtered/sorted group sequence supplied by the UI."""

    await _require_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    client = await _assert_client(db, client_id)
    requested = list(dict.fromkeys(payload.group_ids))
    models = list(
        (
            await db.execute(
                select(ClientOrderGroup).where(
                    ClientOrderGroup.client_id == client_id,
                    ClientOrderGroup.id.in_(requested),
                )
            )
        ).scalars()
    )
    by_id = {group.id: group for group in models}
    if any(group_id not in by_id for group_id in requested):
        # Same response for an absent ID and an ID belonging to another client.
        raise HTTPException(404, detail="Nie znaleziono zamówienia u tego klienta")

    shared_md_used_by_group = await shared_md_used_totals(
        db, (group.id for group in models if uses_shared_md_pool(group))
    )
    rows: list[OrderExportRow] = []
    for group_id in requested:
        group = await _group_to_read(
            db,
            by_id[group_id],
            with_finance=await _can_see_finance(db, user, client_id),
            precomputed_md_budget_used=(
                shared_md_used_by_group[group_id]
                if uses_shared_md_pool(by_id[group_id])
                else None
            ),
        )
        rows.extend(export_rows_for_group(group))

    content = await run_in_threadpool(
        build_orders_workbook, rows, include_model_columns=True
    )
    filename = orders_export_filename(client_display_name(client))
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/{client_id}/order-groups/consultant-options",
    response_model=ConsultantOptionsResponse,
)
async def list_consultant_options_for_client(
    client_id: int,
    user: ConsultantOptionsReader,
    q: str = Query("", max_length=120, description="Imię i nazwisko"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Kogo można dołożyć do zamówienia — jedna lista, dwa źródła.

    Osoby z kontraktem u tego klienta ORAZ pozostali aktywni konsultanci z bazy
    Nexus, scaleni, bez duplikatów i posortowani alfabetycznie po imieniu.
    Każda pozycja niesie etykietę pochodzenia, bo wybór między dwiema osobami
    o tym samym nazwisku bywa wyborem między „ta, którą tu znamy" a „ta z bazy".

    Lista jest odczytem biznesowym: Finance może sprawdzić dostępne osoby i
    sugerowane stawki w całej organizacji, ale nie zyskuje przez to prawa do
    ``add_line`` ani żadnej innej mutacji grupy.
    """
    await _require_group_read(db, user, client_id)

    options, total = await list_consultant_options(
        db, client_id=client_id, query=q, limit=limit
    )
    include_rate_suggestions = await _can_see_finance(db, user, client_id)
    return ConsultantOptionsResponse(
        options=[
            ConsultantOptionRead(
                candidate_id=o.candidate_id,
                contract_id=o.contract_id,
                full_name=o.full_name,
                first_name=o.first_name,
                last_name=o.last_name,
                source=o.source,
                source_label=o.source_label,
                job_title=o.job_title,
                # Odczyt stawek jest szerszy od ich zapisu: Finance ma
                # VIEW_FINANCE, ale mutacje linii nadal wymagają admina albo
                # przypisanego Delivery Leada.
                suggested_rate_cost=(
                    o.suggested_rate_cost if include_rate_suggestions else None
                ),
                suggested_contract_rate_cost=(
                    o.suggested_contract_rate_cost if include_rate_suggestions else None
                ),
                suggested_rate_cost_unit=(
                    o.suggested_rate_cost_unit if include_rate_suggestions else None
                ),
                suggested_rate_cost_currency=(
                    o.suggested_rate_cost_currency if include_rate_suggestions else None
                ),
                suggested_rate_cost_rate_to_pln=(
                    o.suggested_rate_cost_rate_to_pln
                    if include_rate_suggestions
                    else None
                ),
                has_different_client_contract_rates=(
                    o.has_different_client_contract_rates
                    if include_rate_suggestions
                    else False
                ),
            )
            for o in options
        ],
        total=total,
    )


@router.get(
    "/{client_id}/order-groups/{group_id}/events",
    response_model=OrderGroupEventsResponse,
)
async def list_group_events(
    client_id: int,
    group_id: int,
    user: OrderGroupSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Historia zamówienia — chronologicznie, od najnowszego."""
    await _require_safe_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    await _load_group(db, client_id, group_id)

    result = await db.execute(
        select(ClientOrderGroupEvent)
        .where(ClientOrderGroupEvent.group_id == group_id)
        .order_by(
            ClientOrderGroupEvent.created_at.desc(), ClientOrderGroupEvent.id.desc()
        )
    )
    with_finance = await _can_see_finance(db, user, client_id)
    events: list[OrderGroupEventRead] = []
    for ev in result.scalars():
        if _is_technical_event(ev.event_type, ev.payload):
            continue
        related_id, related_number = _related_order(group_id, ev)
        # `payload` niesie stawki (rozliczenie faktury w miesiącu zamiany),
        # więc dla ról bez VIEW_FINANCE znika w całości — opis po polsku
        # zostaje, bo mówi KTO i KIEDY, a nie ZA ILE. Odsyłacz do drugiego
        # zamówienia jedzie POZA tą redakcją (patrz `OrderGroupEventRead`).
        events.append(
            OrderGroupEventRead(
                id=ev.id,
                event_type=ev.event_type,
                event_label=EVENT_TYPE_LABELS.get(ev.event_type, ev.event_type),
                description=(
                    EVENT_TYPE_LABELS.get(ev.event_type, ev.event_type)
                    if _is_read_only_tcm(user)
                    else ev.description
                ),
                order_id=ev.order_id,
                payload=ev.payload if with_finance else None,
                created_by_user_id=ev.created_by_user_id,
                created_at=ev.created_at,
                related_group_id=related_id,
                related_order_number=related_number,
            )
        )
    return OrderGroupEventsResponse(events=events)


def _related_order(
    group_id: int, event: ClientOrderGroupEvent
) -> tuple[Optional[int], Optional[str]]:
    """Druga strona przejęcia zużycia MD — do klikalnego numeru w historii.

    Ten sam ``payload`` jest zapisywany po obu stronach podziału, więc która
    strona jest „drugą", rozstrzyga id oglądanej grupy. Wartości z bazy są
    sprawdzane co do typu: dziennik przeżywa dane starsze od dzisiejszego
    kształtu, a niedopasowany wpis ma nie mieć odsyłacza, a nie wywracać
    odczyt całej historii.
    """
    if event.event_type != EVENT_MD_TRANSFER:
        return None, None
    payload = event.payload or {}
    if payload.get("predecessor_group_id") == group_id:
        other_id = payload.get("successor_group_id")
        other_number = payload.get("successor_order_number")
    else:
        other_id = payload.get("predecessor_group_id")
        other_number = payload.get("predecessor_order_number")
    return (
        other_id if isinstance(other_id, int) else None,
        other_number if isinstance(other_number, str) else None,
    )


@router.get("/{client_id}/order-groups/{group_id}/file")
async def download_order_group_file(
    client_id: int,
    group_id: int,
    user: OrderGroupReader,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz master PDF zamówienia wielo-konsultantowego."""

    await _require_group_read(db, user, client_id)
    if not await _can_see_finance(db, user, client_id):
        raise deny("plik zamówienia z kwotami wymaga przypisania do klienta")
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    if not group.file_path:
        raise HTTPException(404, detail="To zamówienie nie ma pliku PDF")
    try:
        path = storage_service.get_client_order_group_po_path(group.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(410, detail="Plik PDF zamówienia nie istnieje") from exc
    return FileResponse(
        path,
        media_type="application/pdf",
        filename=f"{group.order_number}.pdf",
    )


@router.put(
    "/{client_id}/order-groups/{group_id}/file",
    response_model=OrderGroupRead,
)
async def replace_order_group_file(
    client_id: int,
    group_id: int,
    user: DeliveryLeadOrAdmin,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Zapisz master PDF i upsertuj jego kopię na każdym kontrakcie z grupy."""

    await _assert_client(db, client_id)
    if not await _can_see_finance(db, user, client_id):
        raise deny("plik zamówienia z kwotami wymaga przypisania do klienta")
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    filename = file.filename or "zamowienie.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(415, detail="Plik zamówienia musi być PDF-em")
    payload = await file.read(MAX_GROUP_PDF_BYTES + 1)
    if len(payload) > MAX_GROUP_PDF_BYTES:
        raise HTTPException(413, detail="Plik jest za duży (limit 25 MB)")
    if not payload.startswith(b"%PDF-"):
        raise HTTPException(415, detail="Plik nie ma poprawnego formatu PDF")

    previous_master = group.file_path
    master_path, master_size = storage_service.save_client_order_group_po(
        group.id, filename, io.BytesIO(payload)
    )
    superseded_paths = await _sync_group_pdf_documents(
        db, group=group, payload=payload, user=user
    )
    group.filename = filename
    group.file_path = master_path
    group.content_type = "application/pdf"
    group.size_bytes = master_size
    group.file_uploaded_by = user.id
    group.file_uploaded_at = datetime.now(timezone.utc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_file_replaced",
            user_id=user.id,
            details={"group_id": group.id, "filename": filename},
        )
    )
    await commit_order_write(db)
    if previous_master and previous_master != master_path:
        storage_service.delete_client_order_group_po(previous_master)
    for path in superseded_paths:
        storage_service.delete_contract_document(path)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.delete(
    "/{client_id}/order-groups/{group_id}/file",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_order_group_file(
    client_id: int,
    group_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Usuń master i tylko automatyczne kopie PDF z kontraktów.

    Ręczne dokumenty (``source_order_group_id IS NULL``) nie są dotykane.
    Usunięcie samej grupy korzysta z innej ścieżki i zachowuje kopie jako
    historię — tutaj operator jawnie usuwa błędny załącznik z formularza.
    """

    await _assert_client(db, client_id)
    if not await _can_see_finance(db, user, client_id):
        raise deny("plik zamówienia z kwotami wymaga przypisania do klienta")
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    if not group.file_path:
        raise HTTPException(404, detail="To zamówienie nie ma pliku PDF")

    master_path = group.file_path
    linked_documents = list(
        (
            await db.execute(
                select(ContractDocument).where(
                    ContractDocument.source_order_group_id == group.id
                )
            )
        ).scalars()
    )
    contract_paths = [document.file_path for document in linked_documents]
    for document in linked_documents:
        await db.delete(document)
    group.filename = None
    group.file_path = None
    group.content_type = None
    group.size_bytes = None
    group.file_uploaded_by = None
    group.file_uploaded_at = None
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_file_deleted",
            user_id=user.id,
            details={"group_id": group.id},
        )
    )
    await commit_order_write(db)
    storage_service.delete_client_order_group_po(master_path)
    for path in contract_paths:
        storage_service.delete_contract_document(path)


# ── Zapis ───────────────────────────────────────────────────────────────────


@router.post(
    "/{client_id}/order-groups",
    response_model=OrderGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_group(
    client_id: int,
    payload: OrderGroupCreate,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Nowe zamówienie klienta wraz z jedną lub wieloma liniami konsultantów."""
    if payload.lines or payload.budget_amount is not None:
        await _assert_line_finance_write_allowed(
            db,
            user,
            client_id,
            {"rate_cost", "rate_revenue", "budget_amount"},
        )
    if payload.md_budget_total is not None:
        await _assert_line_finance_write_allowed(
            db, user, client_id, {"md_budget_total"}
        )
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")
    explicit_type = payload.order_type is not None
    resolved_type = (
        payload.order_type
        if payload.order_type is not None
        else (OrderType.cost if payload.is_cost_based else OrderType.md)
    )
    try:
        assert_order_type_allowed(client_id, resolved_type)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if not explicit_type and not is_multi_consultant_client(client_id):
        raise HTTPException(
            422,
            detail="Zamówienia grupowe nie są dostępne dla tego klienta",
        )
    is_cyfrowy_polsat = is_cyfrowy_polsat_order_types_client(client_id)
    is_lotte_wedel = is_lotte_wedel_order_types_client(client_id)
    is_special_shared_md_client = client_uses_shared_md_pool(client_id)
    if (
        explicit_type
        and payload.order_type == OrderType.md
        and payload.md_budget_mode is None
    ):
        if payload.is_md_budget_based and not is_special_shared_md_client:
            raise HTTPException(
                422,
                detail=(
                    "Wspólna pula MD jest dostępna tylko dla Cyfrowego Polsatu "
                    "i Lotte Wedel"
                ),
            )
        if is_special_shared_md_client and not payload.is_md_budget_based:
            raise HTTPException(
                422,
                detail="Zamówienie MD tego klienta wymaga wspólnego budżetu MD",
            )
    if not explicit_type and is_cyfrowy_polsat:
        # Standardowe zamówienie CP powstaje w legacy `/orders`. Endpoint grup
        # przyjmuje dokładnie jeden z dwóch specjalnych wariantów, dzięki czemu
        # false/false nie tworzy ukrytego czwartego typu per-line MD.
        if payload.is_cost_based == payload.is_md_budget_based:
            raise HTTPException(
                422,
                detail=(
                    "Dla Cyfrowego Polsatu wybierz dokładnie jeden typ grupy: "
                    "kosztowe albo na MD"
                ),
            )
    elif not explicit_type and is_lotte_wedel:
        # Lotte Wedel nie może już tworzyć zamówień okresowych. Grupa
        # reprezentuje dokładnie jeden z dwóch dozwolonych wariantów i nigdy
        # nie miesza budżetu PLN z pulą MD.
        if payload.is_cost_based == payload.is_md_budget_based:
            raise HTTPException(
                422,
                detail=(
                    "Dla Lotte Wedel wybierz dokładnie jeden typ grupy: "
                    "kosztowe albo na MD"
                ),
            )
    elif not explicit_type and payload.is_md_budget_based:
        raise HTTPException(
            422,
            detail=(
                "Wspólna pula MD jest dostępna tylko dla Cyfrowego Polsatu "
                "i Lotte Wedel"
            ),
        )
    if payload.is_cost_based and not explicit_type:
        try:
            assert_cost_order_client(client_id)
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    group = ClientOrderGroup(
        client_id=client_id,
        order_number=payload.order_number.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=payload.notes,
        order_type=(
            payload.order_type.value if payload.order_type is not None else None
        ),
        status="draft"
        if payload.status == "draft"
        else _initial_group_status(payload.start_date),
        md_budget_mode=payload.md_budget_mode,
        md_budget_mode_locked=payload.status != "draft",
        is_cost_based=payload.is_cost_based,
        is_md_budget_based=payload.is_md_budget_based,
        budget_amount=payload.budget_amount,
        # Startowa reszta = pełna kwota. Zamówienie kosztowe bez tej wartości
        # naruszyłoby CHECK spójności już przy INSERT-cie.
        budget_remaining=payload.budget_amount,
        md_budget_total=payload.md_budget_total,
        md_budget_remaining=payload.md_budget_total,
        created_by_user_id=user.id,
    )
    db.add(group)
    await db.flush()

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_ORDER_CREATED,
        description=(
            f"Utworzono zamówienie nr {group.order_number} "
            f"({group.start_date.isoformat()} → "
            f"{group.end_date.isoformat() if group.end_date else 'bezterminowo'})"
        ),
        user_id=user.id,
    )

    for line_payload in payload.lines:
        line, who, contract_created = await _build_line(
            db, group=group, payload=line_payload, user=user
        )
        await db.flush()
        await _sync_contract_after_live_group_line(db, line, actor_id=user.id)
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_CONSULTANT_ADDED,
            description=_describe_line(
                line, who, group=group, contract_created=contract_created
            ),
            payload={
                "consultant": who,
                "rate_cost": str(line.md_rate_cost),
                "rate_revenue": str(line.md_rate_revenue),
                "md_total": str(line.md_total),
                "input_mode": line.md_input_mode,
                "input_value": str(line.md_input_value),
                "contract_created": contract_created,
            },
            user_id=user.id,
        )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_created",
            details={
                "group_id": group.id,
                "lines": len(payload.lines),
                "is_cost_based": group.is_cost_based,
                "is_md_budget_based": group.is_md_budget_based,
                "order_type": group.order_type,
            },
        )
    )
    await commit_order_write(db)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.patch("/{client_id}/order-groups/{group_id}", response_model=OrderGroupRead)
async def update_order_group(
    client_id: int,
    group_id: int,
    payload: OrderGroupUpdate,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja numeru i okresu zamówienia (bez dotykania linii)."""
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return await _group_to_read(
            db,
            group,
            with_finance=await _can_see_finance(db, user, client_id),
        )

    # Contract offboarding locks the affected line before it creates a pending
    # decision.  Use the same lock order here so a concurrent PATCH cannot
    # observe "no case yet" and then reactivate or financially change that
    # line after the case has been created.
    await db.execute(
        select(ClientOrder.id)
        .where(ClientOrder.order_group_id == group.id)
        .order_by(ClientOrder.id)
        .with_for_update()
    )
    await _assert_no_pending_offboarding_case(db, group_id=group.id)
    await _normalize_empty_explicit_md_group(db, group)

    consumption_month = data.pop("md_consumption_month", None)
    consumption_value = data.pop("md_consumption_value", None)
    if (consumption_month is None) != (consumption_value is None):
        raise HTTPException(422, detail="Podaj miesiąc i liczbę wykorzystanych MD")
    if consumption_month is not None:
        await _assert_line_finance_write_allowed(
            db, user, client_id, {"md_budget_total"}
        )
        if not uses_shared_md_pool(group) or group.status not in (
            GROUP_STATUS_ACTIVE,
            GROUP_STATUS_EXHAUSTED,
        ):
            raise HTTPException(
                409,
                detail="Zużycie MD wpisuje się na aktywnym zamówieniu ze wspólną pulą",
            )
        await upsert_shared_md_consumption(
            db,
            group=group,
            period_month=consumption_month,
            md_reported=consumption_value,
            source="manual",
            user_id=user.id,
        )
        record_event(
            db,
            group_id=group.id,
            event_type=EVENT_MANUAL_EDIT,
            description=f"Zużycie wspólnej puli MD za {consumption_month}: {consumption_value} MD",
            user_id=user.id,
        )

    requested_mode = data.pop("md_budget_mode", group.md_budget_mode)
    requested_status = data.pop("status", None)
    if requested_mode != group.md_budget_mode or requested_status is not None:
        group = await lock_group_for_settlement(db, group, flush_local_changes=False)
        if (
            group.md_budget_mode is None
            or group.status != "draft"
            or (requested_mode != group.md_budget_mode and group.md_budget_mode_locked)
        ):
            raise HTTPException(
                409,
                detail="Tryb budżetu można zmieniać tylko w nowym szkicu bez zużycia MD",
            )
        consumed = await db.scalar(
            select(ClientOrderGroupMdConsumption.id)
            .where(ClientOrderGroupMdConsumption.group_id == group.id)
            .limit(1)
        )
        line_consumed = await db.scalar(
            select(ClientOrderMdConsumption.id)
            .join(ClientOrder, ClientOrder.id == ClientOrderMdConsumption.order_id)
            .where(ClientOrder.order_group_id == group.id)
            .limit(1)
        )
        if requested_mode != group.md_budget_mode and (
            consumed is not None or line_consumed is not None
        ):
            raise HTTPException(409, detail="Zamówienie ma już wpis zużycia MD")
        if requested_mode not in ("per_person", "shared"):
            raise HTTPException(422, detail="Nieprawidłowy tryb budżetu MD")
        if requested_mode != group.md_budget_mode:
            draft_lines = await lines_for_group(db, group.id)
            if any(
                line.md_manual_adjustment
                or (line.md_total or 0) != (line.md_remaining or 0)
                for line in draft_lines
            ):
                raise HTTPException(409, detail="Linie mają już zużycie lub korektę MD")
            group.md_budget_mode = requested_mode
            group.is_md_budget_based = requested_mode == "shared"
            if group.is_md_budget_based:
                total = data.get("md_budget_total")
                if total is None or total <= 0:
                    raise HTTPException(422, detail="Podaj wspólny budżet MD")
                group.md_budget_total = total
                group.md_budget_remaining = total
                for line in draft_lines:
                    line.md_total = line.md_remaining = line.md_input_value = (
                        line.md_input_mode
                    ) = None
            else:
                group.md_budget_total = group.md_budget_remaining = None
                group.md_budget_manual_adjustment = Decimal("0")
                data.pop("md_budget_total", None)
                for line in draft_lines:
                    line.md_total = line.md_remaining = line.md_input_value = Decimal(
                        "0"
                    )
                    line.md_input_mode = "md"
        if requested_status == "active":
            draft_lines = await lines_for_group(db, group.id)
            if not draft_lines or (
                requested_mode == "per_person"
                and any(not line.md_total for line in draft_lines)
            ):
                raise HTTPException(
                    422,
                    detail="Przed aktywacją dodaj konsultantów i uzupełnij ich budżety MD",
                )
            group.status = GROUP_STATUS_SCHEDULED
            group.md_budget_mode_locked = True
        await db.flush()

    new_start = data.get("start_date", group.start_date)
    new_end = data.get("end_date", group.end_date)
    if new_end and new_start and new_end < new_start:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")

    cost_budget_fields = {"budget_amount", "budget_manual_adjustment"}
    md_budget_fields = {"md_budget_total", "md_budget_manual_adjustment"}
    await _assert_line_finance_write_allowed(
        db,
        user,
        client_id,
        set(data) & (cost_budget_fields | md_budget_fields),
    )
    if data.keys() & cost_budget_fields and not group.is_cost_based:
        raise HTTPException(
            422,
            detail="Kwotę zamówienia można zmieniać tylko na zamówieniu kosztowym",
        )
    if data.keys() & md_budget_fields and not uses_shared_md_pool(group):
        raise HTTPException(
            422,
            detail="Wspólny budżet MD można zmieniać tylko na zamówieniu na MD",
        )
    if data.keys() & (cost_budget_fields | md_budget_fields):
        # Lines were locked above before applying the operator's PLN/MD budget
        # edit.  Lock the group next so the later before/after event and
        # exhausted alert use one serialized state.
        group = await lock_group_for_settlement(db, group, flush_local_changes=False)
    # Jawny `null` przechodzi walidację schematu (pole jest Optional), ale na
    # zamówieniu kosztowym narusza CHECK spójności — czyli IntegrityError i 500
    # zamiast czytelnej odmowy.
    if "budget_amount" in data and data["budget_amount"] is None:
        raise HTTPException(
            422,
            detail=(
                "Zamówienie kosztowe musi mieć kwotę. Aby je zamknąć, użyj "
                "zakończenia zamówienia."
            ),
        )
    if "budget_manual_adjustment" in data and data["budget_manual_adjustment"] is None:
        raise HTTPException(422, detail="Korekta kwoty nie może być pusta")
    if "md_budget_total" in data and data["md_budget_total"] is None:
        raise HTTPException(
            422,
            detail=(
                "Zamówienie na MD musi mieć wspólny budżet. Aby je zamknąć, "
                "użyj zakończenia zamówienia."
            ),
        )
    if (
        "md_budget_manual_adjustment" in data
        and data["md_budget_manual_adjustment"] is None
    ):
        raise HTTPException(422, detail="Korekta budżetu MD nie może być pusta")

    previous_start_date = group.start_date
    previous_end_date = group.end_date
    for field, value in data.items():
        setattr(group, field, value.strip() if field == "order_number" else value)

    if data.keys() & {"order_number", "start_date", "end_date"}:
        group_lines = await lines_for_group(db, group.id)
        for line in group_lines:
            if "order_number" in data:
                who = consultant_display_name(line) or "konsultant"
                line.title = f"Zamówienie {group.order_number} — {who}"[:255]
            if "start_date" in data and (
                group.status == GROUP_STATUS_SCHEDULED
                or line.start_date == previous_start_date
            ):
                line.start_date = group.start_date
            if "end_date" in data and (
                group.status == GROUP_STATUS_SCHEDULED
                or line.end_date == previous_end_date
            ):
                line.end_date = group.end_date
        # Przesunięcie daty końca zdejmuje z linii MD jedyny powód, dla którego
        # mogła zostać kiedyś domknięta datą (skaner robił to do tej rewizji),
        # więc stan trzeba przeliczyć od nowa — sam status linii schodzi już
        # wyłącznie z budżetu. Tylko na zamówieniu AKTYWNYM: wskrzeszona linia
        # w zamówieniu zakończonym dałaby kartę, której interfejs nie umie
        # wytłumaczyć (nagłówek „zakończone", pod nim pracujący konsultant).
        if group.status == GROUP_STATUS_ACTIVE:
            for line in group_lines:
                await sync_md_line_status(db, line)

    if data.keys() & cost_budget_fields:
        # Zmiana kwoty MUSI przeliczyć rozliczenie od zera, a nie tylko
        # podmienić liczbę: podniesienie budżetu odsłania kwoty, które
        # wcześniej się nie zmieściły, a bez przeliczenia zostałyby
        # „nierozliczone" mimo dostępnych pieniędzy.
        was_exhausted = group.status == GROUP_STATUS_EXHAUSTED
        await settle_group(db, group)
        if not was_exhausted and group.status == GROUP_STATUS_EXHAUSTED:
            record_event(
                db,
                group_id=group.id,
                event_type=EVENT_BUDGET_EXHAUSTED,
                description=(
                    f"Budżet zamówienia {group.order_number} wyczerpany "
                    "po korekcie kwoty."
                ),
                user_id=user.id,
            )
            await emit_cost_order_exhausted(db, group)

    if data.keys() & md_budget_fields and uses_shared_md_pool(group):
        was_exhausted = group.status == GROUP_STATUS_EXHAUSTED
        await settle_shared_md_group(db, group)
        if not was_exhausted and group.status == GROUP_STATUS_EXHAUSTED:
            record_event(
                db,
                group_id=group.id,
                event_type=EVENT_BUDGET_EXHAUSTED,
                description=(
                    f"Budżet MD zamówienia {group.order_number} wyczerpany po korekcie."
                ),
                user_id=user.id,
            )
            await emit_shared_md_pool_exhausted(db, group)

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_MANUAL_EDIT,
        description="Edycja zamówienia: " + ", ".join(sorted(data.keys())),
        payload={"changed": sorted(data.keys())},
        user_id=user.id,
    )
    # Edycja danych przyszłego zamówienia celowo NIE regeneruje ani nie
    # przemianowuje historycznej kopii PDF w kontrakcie. Kopię aktualizuje
    # wyłącznie jawne podmienienie pliku przez endpoint PUT .../file.
    await materialize_scheduled_order_groups(db, client_id=client_id)
    await commit_order_write(db)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.delete(
    "/{client_id}/order-groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_order_group(
    client_id: int,
    group_id: int,
    user: OrderLifecycleUser,
    db: AsyncSession = Depends(get_db),
):
    """Usuwa błędnie założone zamówienie WRAZ z jego liniami.

    Do 0233 zamówienie z liniami było odrzucane (409) — wtedy nie było czym
    linii usunąć, więc jedynym wyjściem było zostawienie pomyłki w rejestrze.
    Teraz każda linia przechodzi przez tę samą regułę co
    ``DELETE …/lines/{id}``: znika tylko szkic bez śladów, a linia z historią
    jest ODPINANA od zamówienia, nie kasowana.

    **Usunięcie nie zostawia wpisu w historii** (wymóg ticketu) — dziennik
    zamówienia znika razem z nim (``ON DELETE CASCADE``).
    """
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    master_path = group.file_path

    lines_result = await db.execute(
        _line_query()
        .where(ClientOrder.order_group_id == group.id)
        .order_by(ClientOrder.id.asc())
        .with_for_update()
    )
    lines = list(lines_result.scalars().unique().all())
    await _assert_no_pending_offboarding_case(db, group_id=group.id)
    await _assert_group_is_disposable(db, group, lines)
    detached = 0
    for line in lines:
        if await _detach_or_delete_line(db, line):
            detached += 1

    await db.flush()
    await db.delete(group)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_deleted",
            details={
                "group_id": group_id,
                "lines_removed": len(lines),
                "lines_detached": detached,
            },
        )
    )
    await commit_order_write(db)
    # Automatyczne kopie na kontraktach są osobnymi plikami i pozostają jako
    # zapis historyczny (FK źródła przechodzi na NULL). Master należący do
    # usuniętej grupy nie ma już konsumenta, więc można go bezpiecznie zwolnić.
    if master_path:
        storage_service.delete_client_order_group_po(master_path)


async def _assert_group_is_disposable(
    db: AsyncSession, group: ClientOrderGroup, lines: list[ClientOrder]
) -> None:
    """Twardo kasować wolno tylko zamówienie, po którym nic nie zostało.

    Ta sama ostrożność co w ``_detach_or_delete_line``, tyle że o poziom wyżej.
    Tam była stosowana od początku — „zamówienie konsultanta niesie kontrakt,
    plik od klienta i historię rozliczeń" — ale samo zamówienie znikało
    BEZWARUNKOWO, choć niesie więcej: własny dziennik zdarzeń (kasowany
    kaskadowo), miesięczne rozliczenia wspólnej puli MD i wgrany dokument PO.
    Linie z historią były odpinane i przeżywały, więc wyglądało to na
    bezpieczne — a znikał cały ślad, na podstawie którego wystawiono faktury.

    Asymetria nie była decyzją: docstring `delete_order_group` uzasadnia
    kasowanie LINII razem z zamówieniem („do 0233 zamówienie z liniami było
    odrzucane 409"), a nie kasowanie zamówienia z rozliczeniami. Ticket
    wymagał, żeby dało się usunąć POMYŁKĘ — i to zostaje możliwe.

    Nie blokujemy zakończonych ani wyczerpanych: „zakończone" to normalny
    koniec życia, a nie powód, żeby wiersz był nieusuwalny. Nie blokuje też
    wgrany PDF — jego los przy kasowaniu jest osobno przemyślany. Blokuje
    wyłącznie ŚLAD ROZLICZENIOWY: pieniądze i dni, które ktoś już zaraportował.
    """
    blockers: list[str] = []

    # Wgrany PDF NIE blokuje — to świadoma, obsłużona ścieżka: automatyczne
    # kopie na kontraktach zostają jako zapis historyczny (FK źródła idzie na
    # NULL), a master usuniętej grupy nie ma już konsumenta. Traktowanie pliku
    # jak śladu rozliczeniowego wywracało `test_deleting_future_group_keeps_
    # pdf_as_historical_contract_document`, czyli regresję tej decyzji.
    shared_md_months = await db.scalar(
        select(func.count(ClientOrderGroupMdConsumption.id)).where(
            ClientOrderGroupMdConsumption.group_id == group.id
        )
    )
    if shared_md_months:
        blockers.append(f"rozliczone miesiące wspólnej puli MD ({shared_md_months})")

    line_ids = [line.id for line in lines]
    if line_ids:
        md_rows = await db.scalar(
            select(func.count(ClientOrderMdConsumption.id)).where(
                ClientOrderMdConsumption.order_id.in_(line_ids)
            )
        )
        if md_rows:
            blockers.append(f"rozliczone MD konsultantów ({md_rows})")
        invoice_rows = await db.scalar(
            select(func.count(ClientOrderInvoiceConsumption.id)).where(
                ClientOrderInvoiceConsumption.order_id.in_(line_ids)
            )
        )
        if invoice_rows:
            blockers.append(f"zaimportowane faktury ({invoice_rows})")

    if not blockers:
        return

    raise HTTPException(
        409,
        detail=(
            "Tego zamówienia nie można usunąć, bo są na nim rozliczenia: "
            + ", ".join(blockers)
            + ". Usunięcie skasowałoby też jego historię. Jeżeli współpraca "
            "się skończyła — użyj „Zakończ”. Jeżeli to pomyłka do wycofania, "
            "najpierw usuń z niego rozliczenia."
        ),
    )


async def _detach_or_delete_line(db: AsyncSession, line: ClientOrder) -> bool:
    """Usuń linię z zamówienia. Zwraca ``True``, gdy została ODPIĘTA, nie skasowana.

    Twarde kasowanie tylko dla linii, po której nic nie zostało: szkic bez
    pliku PO, bez notatek i bez zużycia. Ta sama reguła co przy
    ``DELETE /api/clients/{c}/orders/{o}`` — zamówienie konsultanta niesie
    kontrakt, plik od klienta i historię rozliczeń, a te powstały poza tym
    ekranem i nie są niczyją pomyłką do sprzątnięcia.

    Wpisy historii dotyczące TEJ linii („dodanie konsultanta") znikają razem
    z nią, bo ticket żąda, żeby błędnie dodana osoba zniknęła bez śladu.
    Zdarzenia zamiany kontraktora ZOSTAJĄ: mówią o dwóch osobach naraz, więc
    skasowanie ich zabrałoby informację także tej drugiej.
    """
    consumption_count = await db.scalar(
        select(func.count(ClientOrderMdConsumption.id)).where(
            ClientOrderMdConsumption.order_id == line.id
        )
    )
    invoice_count = await db.scalar(
        select(func.count(ClientOrderInvoiceConsumption.id)).where(
            ClientOrderInvoiceConsumption.order_id == line.id
        )
    )
    has_history = bool(consumption_count or invoice_count or line.file_path)
    disposable = line.status == ClientOrderStatus.draft and not has_history

    await db.execute(
        delete(ClientOrderGroupEvent).where(
            ClientOrderGroupEvent.order_id == line.id,
            ClientOrderGroupEvent.event_type == EVENT_CONSULTANT_ADDED,
        )
    )

    if disposable:
        await db.delete(line)
        return False

    line.order_group_id = None
    return True


@router.delete(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_line(
    client_id: int,
    group_id: int,
    line_id: int,
    user: OrderLifecycleUser,
    db: AsyncSession = Depends(get_db),
):
    """Usuwa POJEDYNCZEGO konsultanta z zamówienia; reszta zostaje bez zmian.

    Osobna trasa od kasowania całego zamówienia, bo to dwie różne decyzje:
    „dodałem nie tę osobę" i „założyłem nie to zamówienie". Ticket żąda obu
    jako oddzielnych opcji właśnie dlatego, że jedno zamówienie obejmuje
    kilku konsultantów.
    """
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    line = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == line_id, ClientOrder.order_group_id == group.id)
        .with_for_update()
    )
    if line is None:
        raise HTTPException(404, detail="Ta linia nie należy do tego zamówienia")

    await _assert_no_pending_offboarding_case(db, group_id=group.id, order_id=line.id)

    detached = await _detach_or_delete_line(db, line)
    if group.is_cost_based:
        # Kasowanie linii zabiera też jej faktury (CASCADE), więc pula musi
        # zostać przeliczona — inaczej zamówienie zostaje „wyczerpane" kwotami,
        # których już w bazie nie ma.
        await db.flush()
        await settle_group(db, group)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_line_deleted",
            details={
                "group_id": group_id,
                "order_id": line_id,
                "detached": detached,
            },
        )
    )
    await commit_order_write(db)


@router.post(
    "/{client_id}/order-groups/{group_id}/close", response_model=OrderGroupRead
)
async def close_order_group(
    client_id: int,
    group_id: int,
    payload: OrderGroupClose,
    user: OrderLifecycleUser,
    db: AsyncSession = Depends(get_db),
):
    """Zakończenie zamówienia — konsultant kończy współpracę u klienta.

    Domknięcie linii jest LUSTREM syncu terminacji kontraktu
    (``contracts.py``): data zakończenia zapisuje się zawsze, ale status
    ``completed`` dostają wyłącznie linie, których dzień zakończenia już
    nadszedł. Bez tego rozróżnienia zakończenie zaplanowane na przyszłość
    wyłączałoby konsultanta, który dziś jeszcze pracuje.
    """
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    if group.status == GROUP_STATUS_COMPLETED:
        raise HTTPException(409, detail="To zamówienie jest już zakończone")
    # Data wcześniejsza niż start zamówienia narusza `ck_client_order_groups_dates`
    # (przepisujemy nią `end_date`) — bez tej bramki wychodzi 500 zamiast
    # informacji, że data jest niemożliwa.
    if payload.closure_date < group.start_date:
        raise HTTPException(
            422,
            detail=(
                "Data zakończenia jest wcześniejsza niż początek zamówienia "
                f"({group.start_date.isoformat()})."
            ),
        )

    # Close and contract offboarding both write the line end date.  Lock every
    # line in the same deterministic order before either group or lines are
    # mutated; whichever lifecycle action wins becomes the authoritative one,
    # and an already-pending MD decision cannot be invalidated by closing the
    # whole order behind it.
    locked_lines_result = await db.execute(
        _line_query()
        .where(ClientOrder.order_group_id == group.id)
        .order_by(ClientOrder.id.asc())
        .with_for_update()
    )
    locked_lines = list(locked_lines_result.scalars().unique().all())
    await _assert_no_pending_offboarding_case(db, group_id=group.id)

    # `business_today()`, nie `date.today()` — ten sam dzień graniczny, którym
    # cykl życia grupy posługuje się wszędzie indziej (`_initial_group_status`,
    # `materialize_scheduled_order_groups`). Kontener chodzi w UTC, więc między
    # 22:00 UTC a północą zakończenie „z dniem dzisiejszym" wg firmy nie
    # domykałoby linii, bo dla `date.today()` ta data leży jeszcze w przyszłości.
    today = business_today()
    group.status = GROUP_STATUS_COMPLETED
    group.closure_date = payload.closure_date
    group.closure_reason = (payload.closure_reason or "").strip() or None
    group.closed_at = datetime.now(timezone.utc)
    group.closed_by_user_id = user.id
    if group.end_date is None or group.end_date > payload.closure_date:
        group.end_date = payload.closure_date

    closed_lines = 0
    for line in locked_lines:
        if line.status in (ClientOrderStatus.completed, ClientOrderStatus.cancelled):
            continue
        if line.end_date is None or line.end_date > payload.closure_date:
            line.end_date = payload.closure_date
        if payload.closure_date <= today:
            line.status = ClientOrderStatus.completed
        closed_lines += 1

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_ORDER_CLOSED,
        description=(
            f"Zakończono zamówienie {group.order_number} "
            f"z dniem {payload.closure_date.isoformat()}"
            + (f" — {group.closure_reason}" if group.closure_reason else "")
        ),
        payload={
            "closure_date": payload.closure_date.isoformat(),
            "closure_reason": group.closure_reason,
            "lines_closed": closed_lines,
        },
        user_id=user.id,
    )
    await commit_order_write(db)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.post(
    "/{client_id}/order-groups/{group_id}/reopen", response_model=OrderGroupRead
)
async def reopen_order_group(
    client_id: int,
    group_id: int,
    user: OrderLifecycleUser,
    db: AsyncSession = Depends(get_db),
):
    """Cofnięcie omyłkowego zakończenia — zamówienie wraca z archiwum.

    Przywrócić da się WYŁĄCZNIE zamówienie zakończone ręcznie. Wyczerpane
    (``exhausted``) zwraca 409: tam problemem nie jest błędna data, tylko brak
    pieniędzy, więc właściwą akcją jest korekta kwoty albo nowe zamówienie —
    przywrócenie zostawiłoby zamówienie z zerową pulą, które i tak niczego nie
    przyjmie. Zaplanowane (``scheduled``) też zwraca 409 — patrz niżej.
    """
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    # Serialize with contract offboarding before checking for its pending case.
    # Without the line locks, a same-day reopen could race the case insert and
    # make an ended consultant active again behind the decision workflow.
    await db.execute(
        select(ClientOrder.id)
        .where(ClientOrder.order_group_id == group.id)
        .order_by(ClientOrder.id)
        .with_for_update()
    )
    await _assert_no_pending_offboarding_case(db, group_id=group.id)

    assert_group_is_reopenable(group.status)

    previous_closure = group.closure_date
    group.status = GROUP_STATUS_ACTIVE
    group.closure_date = None
    group.closure_reason = None
    group.closed_at = None
    group.closed_by_user_id = None

    # Przywrócenie musi objąć LINIE, nie tylko nagłówek. Do tej rewizji reopen
    # cofał sam status grupy, a konsultantów zostawiał `completed` — zamówienie
    # wracało do Aktywnych bez ani jednej osoby, więc import zużycia MD dalej go
    # nie widział (`active_md_lines` pyta o linie aktywne) i budżet stał w
    # miejscu. Wskrzeszamy wyłącznie linie z niewyczerpanym budżetem, których
    # okres jeszcze trwa: zakończenie z datą w przeszłości było świadomą
    # decyzją o okresie i reopen jej nie unieważnia (patrz `sync_md_line_status`).
    lines_reopened = 0
    for line in await lines_for_group(db, group.id):
        if await sync_md_line_status(db, line):
            lines_reopened += 1

    record_event(
        db,
        group_id=group.id,
        event_type=EVENT_ORDER_REOPENED,
        description=(
            f"Przywrócono zamówienie {group.order_number} "
            f"(cofnięto zakończenie z dnia "
            f"{previous_closure.isoformat() if previous_closure else '—'})"
        ),
        payload={
            "previous_closure_date": (
                previous_closure.isoformat() if previous_closure else None
            ),
            "lines_reopened": lines_reopened,
        },
        user_id=user.id,
    )
    await commit_order_write(db)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.post(
    "/{client_id}/order-groups/{group_id}/extend",
    response_model=OrderGroupRead,
    status_code=status.HTTP_201_CREATED,
)
async def extend_order_group(
    client_id: int,
    group_id: int,
    payload: OrderGroupExtend,
    user: OrderLifecycleUser,
    db: AsyncSession = Depends(get_db),
):
    """Przedłużenie: NOWE zamówienie kontynuujące poprzednie.

    Nie jest edycją poprzedniego. Numer, okres i budżety są inne, a poprzednie
    zamówienie musi zostać w rejestrze takie, jakie było — to na jego podstawie
    rozliczono już wystawione faktury. Powiązanie idzie przez
    ``predecessor_group_id``, więc widać, skąd wzięła się kontynuacja.

    Typ rozliczenia DZIEDZICZY się po poprzedniku: przedłużenie zamówienia
    kosztowego jest kosztowe, przedłużenie MD jest MD. Zmiana modelu
    rozliczeniowego w połowie współpracy to nowe zamówienie, nie przedłużenie.
    """
    if (
        payload.lines
        or payload.budget_amount is not None
        or payload.md_budget_total is not None
    ):
        await _assert_line_finance_write_allowed(
            db,
            user,
            client_id,
            {
                "rate_candidate_currency",
                "rate_client_currency",
                "rate_cost",
                "rate_revenue",
                "budget_amount",
                "md_budget_total",
            },
        )
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    source = await _load_group(db, client_id, group_id)
    await _normalize_empty_explicit_md_group(db, source)
    source_uses_shared_md = uses_shared_md_pool(source)
    try:
        assert_order_type_allowed(client_id, effective_group_order_type(source))
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc

    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")
    if source.is_cost_based and payload.budget_amount is None:
        raise HTTPException(
            422, detail="Przedłużenie zamówienia kosztowego wymaga kwoty zamówienia"
        )
    if not source.is_cost_based and payload.budget_amount is not None:
        raise HTTPException(
            422,
            detail="Kwotę zamówienia można podać tylko przy zamówieniu kosztowym",
        )
    if source_uses_shared_md and payload.md_budget_total is None:
        raise HTTPException(
            422, detail="Przedłużenie zamówienia na MD wymaga wspólnego budżetu MD"
        )
    if not source_uses_shared_md and payload.md_budget_total is not None:
        raise HTTPException(
            422,
            detail="Wspólny budżet MD można podać tylko przy zamówieniu na MD",
        )

    group = ClientOrderGroup(
        client_id=client_id,
        order_number=payload.order_number.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=payload.notes,
        order_type=source.order_type,
        # Każde przedłużenie zaczyna jako zaplanowane. Jeśli data już nadeszła,
        # wspólny materializer poniżej od razu aktywuje je i zamknie poprzednika.
        status=GROUP_STATUS_SCHEDULED,
        is_cost_based=source.is_cost_based,
        is_md_budget_based=source_uses_shared_md,
        md_budget_mode=source.md_budget_mode,
        md_budget_mode_locked=True,
        budget_amount=payload.budget_amount,
        budget_remaining=payload.budget_amount,
        md_budget_total=payload.md_budget_total,
        md_budget_remaining=payload.md_budget_total,
        predecessor_group_id=source.id,
        created_by_user_id=user.id,
    )
    db.add(group)
    await db.flush()

    description = (
        f"Zamówienie {group.order_number} przedłuża zamówienie "
        f"{source.order_number} ({group.start_date.isoformat()} → "
        f"{group.end_date.isoformat() if group.end_date else 'bezterminowo'})"
    )
    for target in (source.id, group.id):
        record_event(
            db,
            group_id=target,
            event_type=EVENT_ORDER_EXTENDED,
            description=description,
            payload={
                "predecessor_group_id": source.id,
                "successor_group_id": group.id,
            },
            user_id=user.id,
        )

    for line_payload in payload.lines:
        line, who, contract_created = await _build_line(
            db, group=group, payload=line_payload, user=user
        )
        await db.flush()
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_CONSULTANT_ADDED,
            description=_describe_line(
                line, who, group=group, contract_created=contract_created
            ),
            payload={
                "consultant": who,
                "rate_cost": str(line.md_rate_cost),
                "rate_revenue": str(line.md_rate_revenue),
                "md_total": str(line.md_total),
                "contract_created": contract_created,
            },
            user_id=user.id,
        )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_group_extended",
            details={
                "group_id": group.id,
                "predecessor_group_id": source.id,
                "lines": len(payload.lines),
            },
        )
    )
    await materialize_scheduled_order_groups(db, client_id=client_id)
    await commit_order_write(db)
    await db.refresh(group)
    return await _group_to_read(
        db,
        group,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.post(
    "/{client_id}/order-groups/{group_id}/lines",
    response_model=OrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_line(
    client_id: int,
    group_id: int,
    payload: OrderLineCreate,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Dodaje konsultanta do istniejącego zamówienia."""
    await _assert_line_finance_write_allowed(
        db, user, client_id, {"rate_cost", "rate_revenue"}
    )
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    # Wyczerpane/zakończone zamówienie nie przyjmuje nowych konsultantów.
    # Zaplanowane przyjmuje — model wieloosobowy zakłada, że obsada może być
    # kompletowana już po utworzeniu zamówienia, jeszcze przed jego startem.
    # 409, nie 422: żądanie jest poprawne, to STAN ŚWIATA go odrzuca — i to
    # ten stan trzeba zmienić gdzie indziej (nowe zamówienie albo korekta
    # kwoty), a nie treść żądania.
    if group.status not in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED, "draft"):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Zamówienie {group.order_number} jest "
                f"{GROUP_STATUS_LABELS.get(group.status, group.status).lower()} — "
                "nie można dodać do niego konsultanta."
            ),
        )

    await _normalize_empty_explicit_md_group(db, group)

    line, who, contract_created = await _build_line(
        db, group=group, payload=payload, user=user
    )
    await db.flush()
    await _sync_contract_after_live_group_line(db, line, actor_id=user.id)
    record_event(
        db,
        group_id=group.id,
        order_id=line.id,
        event_type=EVENT_CONSULTANT_ADDED,
        description=_describe_line(
            line, who, group=group, contract_created=contract_created
        ),
        payload={
            "consultant": who,
            "rate_cost": str(line.md_rate_cost),
            "rate_revenue": str(line.md_rate_revenue),
            "md_total": str(line.md_total),
            "contract_created": contract_created,
        },
        user_id=user.id,
    )
    superseded_paths = await _sync_group_pdf_for_new_line(db, group=group, user=user)
    await commit_order_write(db)
    for path in superseded_paths:
        storage_service.delete_contract_document(path)

    # Wspólne `_line_query()`, a nie własna lista loaderów: serializacja linii
    # schodzi przez poprzednika aż do kandydata (`predecessor_consultant_name`),
    # więc płaski `selectinload(predecessor)` zostawia tam leniwą relację —
    # w async SQLAlchemy `MissingGreenlet`, czyli 500 bez nagłówków CORS.
    # Linia z `add_line` poprzednika nie ma, więc dziś by nie wybuchła; kopia
    # loaderów obok kanonicznej jest jednak miną dla pierwszej zmiany kształtu
    # odpowiedzi, a nie oszczędnością.
    refreshed = await db.scalar(_line_query().where(ClientOrder.id == line.id))
    return _line_to_read(
        refreshed,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.patch(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}",
    response_model=OrderLineRead,
)
async def update_line(
    client_id: int,
    group_id: int,
    line_id: int,
    payload: OrderLineUpdate,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja linii: stawki, budżet albo ręczna korekta pozostałych MD."""
    supplied = payload.model_fields_set
    await _assert_line_finance_write_allowed(db, user, client_id, set(supplied))
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    has_group_budget = group.is_cost_based or uses_shared_md_pool(group)
    line_budget_fields = {"input_mode", "input_value", "md_remaining"}
    if has_group_budget and supplied & line_budget_fields:
        raise HTTPException(
            422,
            detail=(
                "To zamówienie ma wspólny budżet całej grupy — nie zmieniaj "
                "budżetu MD przy konsultancie"
            ),
        )

    # `_line_query()` (kanoniczny komplet loaderów), bo płaski
    # `selectinload(predecessor)` ładował samego poprzednika, a `_line_to_read`
    # schodzi z niego na `contract.candidate` (`predecessor_consultant_name`).
    # W async SQLAlchemy to leniwe doczytanie leci `MissingGreenlet` → 500 bez
    # nagłówków CORS, czyli „Network Error" w przeglądarce. Trafiało w KAŻDĄ
    # edycję linii po zamianie kontraktora, i to już PO `commit()` — zmiana
    # zapisywała się, a operator widział błąd bez treści i ponawiał.
    line = await db.scalar(
        _line_query()
        .where(
            ClientOrder.id == line_id,
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
        .with_for_update()
    )
    if line is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")
    await _assert_no_pending_offboarding_case(db, group_id=group.id, order_id=line.id)

    data = payload.model_dump(exclude_unset=True)
    changed: list[str] = []
    raw_rates: dict[str, Decimal] = {}
    for field, currency_field, source_field in (
        ("rate_cost", "rate_candidate_currency", "rate_candidate"),
        ("rate_revenue", "rate_client_currency", "rate_client"),
    ):
        if currency_field in data:
            currency = data[currency_field]
            if currency is None:
                raise HTTPException(422, detail="Waluta nie może być pusta")
            raw = data.get(field)
            if raw is None:
                raw = convert_order_rate(
                    getattr(line, source_field),
                    line.rate_unit or RateUnit.daily,
                    RateUnit.daily,
                    line.billing_hours_per_month or 160,
                )
            if raw is None:
                raise HTTPException(422, detail="Podaj stawkę dla wybranej waluty")
            raw_rates[source_field] = raw
            data[field] = await _canonical_currency_rate(
                db, raw, currency, line.start_date or group.start_date
            )
    if raw_rates:
        # Both source sides are returned/sent as MD by the new editor.
        for source_field in ("rate_candidate", "rate_client"):
            raw_rates.setdefault(
                source_field,
                convert_order_rate(
                    getattr(line, source_field),
                    line.rate_unit or RateUnit.daily,
                    RateUnit.daily,
                    line.billing_hours_per_month or 160,
                ),
            )
        line.rate_unit = RateUnit.daily

    for currency_field in ("rate_candidate_currency", "rate_client_currency"):
        if currency_field in data:
            if data[currency_field] is None:
                raise HTTPException(422, detail="Waluta nie może być pusta")
            setattr(line, currency_field, data[currency_field])
            if currency_field == "rate_client_currency":
                line.currency = data[currency_field]
            changed.append(currency_field)
    if "rate_cost" in data:
        line.rate_candidate = data["rate_cost"]
        line.md_rate_cost = data["rate_cost"]
        changed.append("stawka kosztowa")
    if "rate_revenue" in data:
        line.rate_client = data["rate_revenue"]
    if "end_date" in data:
        line.end_date = data["end_date"]
        changed.append("data zakończenia")

    # Stawka przychodowa i budżet przeliczają md_total razem — zmiana samej
    # stawki przy trybie „kwota" musi zmienić liczbę MD, inaczej zamówienie
    # zaczęłoby opiewać na inną kwotę, niż podpisano.
    recompute_total = not has_group_budget and (
        "rate_revenue" in data or "input_mode" in data or "input_value" in data
    )
    if recompute_total:
        rate_revenue = data.get("rate_revenue", line.md_rate_revenue)
        input_mode = data.get("input_mode", line.md_input_mode) or INPUT_MODE_MD
        input_value = data.get("input_value", line.md_input_value)
        if rate_revenue is None or input_value is None:
            raise HTTPException(
                422, detail="Do przeliczenia budżetu potrzebna jest stawka i wartość"
            )
        try:
            line.md_total = compute_md_total(
                input_mode=input_mode,
                input_value=input_value,
                rate_revenue=rate_revenue,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        line.md_rate_revenue = rate_revenue
        line.md_input_mode = input_mode
        line.md_input_value = input_value
        changed.append("budżet MD")
    elif "rate_revenue" in data:
        # Wspólna pula (kosztowa albo MD) nie zależy od stawki pojedynczej
        # linii. Zmiana stawki nie może próbować odtworzyć nieistniejącego
        # per-line `input_value`.
        line.md_rate_revenue = data["rate_revenue"]
        changed.append("stawka przychodowa")

    if "md_remaining" in data and data["md_remaining"] is not None:
        # Korekta zapisywana jako RÓŻNICA, nie nadpisanie. Nadpisanie
        # `md_remaining` przeżyłoby dokładnie do najbliższego importu, który
        # przelicza pozostałość od `md_total` — i skasowałoby poprawkę bez
        # śladu.
        await recompute_remaining(db, line)
        natural = Decimal(str(line.md_remaining or 0)) - Decimal(
            str(line.md_manual_adjustment or 0)
        )
        line.md_manual_adjustment = quantize_md(
            Decimal(str(data["md_remaining"])) - natural
        )
        changed.append("ręczna korekta MD")

    for source_field, raw in raw_rates.items():
        setattr(line, source_field, raw)

    # Przeliczenie budżetu domyka też status linii (`sync_md_line_status` siedzi
    # w `recompute_remaining`): podniesienie budżetu albo ręczna korekta
    # odsłaniają MD, więc konsultant musi wrócić na `active` — inaczej import
    # zużycia przestaje go widzieć mimo dostępnych dni.
    if not has_group_budget:
        await recompute_remaining(db, line)
    await db.flush()

    if changed:
        record_event(
            db,
            group_id=group_id,
            order_id=line.id,
            event_type=EVENT_MANUAL_EDIT,
            description=(
                f"{consultant_display_name(line)} — zmieniono: "
                + ", ".join(changed)
                + (
                    "."
                    if has_group_budget
                    else f". Pozostało {format_md(line.md_remaining)} MD."
                )
            ),
            payload={
                "changed": changed,
                "md_remaining": (None if has_group_budget else str(line.md_remaining)),
            },
            user_id=user.id,
        )
    await commit_order_write(db)
    await db.refresh(line)
    return _line_to_read(
        line,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.post(
    "/{client_id}/order-groups/{group_id}/offboarding-cases/{case_id}/resolve",
    response_model=OrderOffboardingCaseRead,
)
async def resolve_md_offboarding_case(
    client_id: int,
    group_id: int,
    case_id: int,
    payload: OrderOffboardingResolutionRequest,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Resolve the Delivery Lead decision after an MD consultant leaves.

    Legacy per-line pools are either forfeited or added to another active line.
    New shared-pool orders never assign an implicit personal slice: the group
    budget stays unchanged and the decision only removes the departed line
    from the active workflow. Every branch is locked and versioned so two DLs
    cannot apply the same pool twice.
    """

    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    if not await _has_md_line_management_access(db, user, client_id):
        raise deny("decyzję o puli MD podejmuje Delivery Lead albo administrator")

    group = await db.scalar(
        select(ClientOrderGroup)
        .where(
            ClientOrderGroup.id == group_id,
            ClientOrderGroup.client_id == client_id,
        )
        .with_for_update()
    )
    if group is None:
        raise HTTPException(404, detail="Zamówienie nie istnieje")
    if effective_group_order_type(group) != OrderType.md:
        raise HTTPException(409, detail="Ta decyzja dotyczy wyłącznie zamówień MD")

    case = await db.scalar(
        select(ClientOrderOffboardingCase)
        .where(
            ClientOrderOffboardingCase.id == case_id,
            ClientOrderOffboardingCase.client_id == client_id,
            ClientOrderOffboardingCase.order_group_id == group_id,
        )
        .with_for_update()
    )
    if case is None:
        raise HTTPException(404, detail="Sprawa zakończenia współpracy nie istnieje")
    if case.status != OFFBOARDING_STATUS_PENDING:
        raise HTTPException(
            409,
            detail={
                "code": "offboarding_case_already_resolved",
                "message": "Ta decyzja została już obsłużona.",
                "version": case.version,
            },
        )
    if case.version != payload.expected_version:
        raise HTTPException(
            409,
            detail={
                "code": "offboarding_case_version_conflict",
                "message": "Sprawa zmieniła się w innym oknie. Odśwież zamówienie.",
                "version": case.version,
            },
        )

    # Resolve i operacje grupowe mogą dotykać dwóch tych samych linii. Blokuj
    # source + target jednym zapytaniem w rosnącym porządku ID; osobne locki
    # source→target tworzyłyby cykl z close/reopen/delete, które poprawnie
    # blokują wszystkie linie grupy rosnąco.
    line_ids = [case.order_id]
    if (
        payload.action == OFFBOARDING_RESOLUTION_TRANSFER
        and payload.target_order_id is not None
    ):
        line_ids.append(payload.target_order_id)
    locked_lines_result = await db.execute(
        _line_query()
        .where(
            ClientOrder.id.in_(line_ids),
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
        .order_by(ClientOrder.id.asc())
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    locked_lines = {
        line.id: line for line in locked_lines_result.scalars().unique().all()
    }
    source = locked_lines.get(case.order_id)
    if source is None:
        raise HTTPException(409, detail="Linia odchodzącego konsultanta nie istnieje")

    remaining = max(Decimal("0"), quantize_md(case.remaining_md_snapshot))
    transferred_md = Decimal("0")
    target: Optional[ClientOrder] = None
    target_name: Optional[str] = None
    source_rate = case.rate_revenue_snapshot or source.md_rate_revenue
    target_rate: Optional[Decimal] = None

    if payload.action == OFFBOARDING_RESOLUTION_TRANSFER:
        target = locked_lines.get(payload.target_order_id)
        if target is None:
            raise HTTPException(
                422, detail="Wskazany konsultant nie jest na zamówieniu"
            )
        if target.id == source.id:
            raise HTTPException(422, detail="Nie można przenieść puli na tę samą osobę")
        if (
            source.contract is not None
            and target.contract is not None
            and source.contract.candidate_id == target.contract.candidate_id
        ):
            raise HTTPException(
                422, detail="Nie można przenieść puli na drugi wpis tej samej osoby"
            )
        if target.status != ClientOrderStatus.active:
            raise HTTPException(409, detail="Konsultant docelowy nie jest już aktywny")
        target_name = consultant_display_name(target)
        target_rate = target.md_rate_revenue
        if target_rate is None or target_rate <= 0:
            raise HTTPException(
                422, detail="Konsultant docelowy nie ma stawki przychodowej"
            )

        if not case.uses_shared_md_pool:
            if target.md_total is None:
                raise HTTPException(422, detail="Linia docelowa nie ma budżetu MD")
            basis_rate = (
                source_rate
                if payload.rate_basis == OFFBOARDING_RATE_BASIS_DEPARTING
                else target_rate
            )
            if basis_rate is None or basis_rate <= 0:
                raise HTTPException(422, detail="Brak stawki do przeliczenia puli MD")
            transferred_md = quantize_md(remaining * basis_rate / target_rate)
            target.md_total = quantize_md(
                Decimal(str(target.md_total)) + transferred_md
            )
            if target.md_input_mode == INPUT_MODE_AMOUNT:
                target.md_input_value = quantize_md(
                    Decimal(str(target.md_input_value or 0))
                    + transferred_md * target_rate
                )
            else:
                target.md_input_mode = INPUT_MODE_MD
                target.md_input_value = quantize_md(
                    Decimal(str(target.md_input_value or 0)) + transferred_md
                )
            await recompute_remaining(db, target)

    restored_end_date: Optional[date] = None
    contract_reopened = False
    if payload.action == OFFBOARDING_RESOLUTION_RESTORE:
        restored_end_date, contract_reopened = await _restore_offboarded_line(
            db,
            case=case,
            group=group,
            source=source,
            requested_end_date=payload.restore_end_date,
            actor_id=user.id,
        )

    # A legacy line's unused pool is removed from its signed value. Consumption
    # stays untouched; cards and exports now show the reduced total instead of
    # pretending the forfeited/transferred remainder was consumed.
    #
    # ``restore`` jest tu WYKLUCZONE, i to jest cała jego istota: pula nie
    # została ani przekazana, ani utracona — współpraca trwa dalej, więc
    # zdjęcie jej z wartości zamówienia byłoby zapisaniem faktu, który się nie
    # wydarzył (i zabraniem konsultantowi budżetu, na którym właśnie pracuje).
    if (
        payload.action != OFFBOARDING_RESOLUTION_RESTORE
        and not case.uses_shared_md_pool
        and source.md_total is not None
        and remaining > 0
    ):
        _reduce_legacy_md_budget(source, remaining)
        await recompute_remaining(db, source)

    now = datetime.now(timezone.utc)
    case.status = OFFBOARDING_STATUS_RESOLVED
    case.resolution = payload.action
    case.target_order_id = target.id if target is not None else None
    case.rate_basis = payload.rate_basis
    case.resolved_at = now
    case.resolved_by_user_id = user.id
    case.version += 1
    case.resolution_payload = {
        "remaining_md_snapshot": str(remaining),
        "transferred_md": str(transferred_md),
        "uses_shared_md_pool": case.uses_shared_md_pool,
        "source_rate_revenue": None if source_rate is None else str(source_rate),
        "target_rate_revenue": None if target_rate is None else str(target_rate),
        "target_order_id": target.id if target is not None else None,
        "target_consultant": target_name,
        # Horyzont przywrócenia i to, czy trzeba było wskrzesić kontrakt —
        # jedyny trwały ślad tej decyzji poza wpisem w historii. Oryginalna
        # data końca linii przepadła przy offboardingu (case snapshotuje pulę
        # i stawki, nie okres), więc nowa data JEST decyzją, nie odtworzeniem.
        "restored_end_date": (
            None if restored_end_date is None else restored_end_date.isoformat()
        ),
        "contract_reopened": contract_reopened,
    }

    source_name = consultant_display_name(source)
    if payload.action == OFFBOARDING_RESOLUTION_RESTORE:
        event_type = EVENT_MD_OFFBOARDING_RESTORED
        horizon = (
            "bezterminowo"
            if restored_end_date is None
            else f"do {restored_end_date.isoformat()}"
        )
        description = (
            f"{source_name} — współpraca trwa dalej: linia wróciła na aktywną "
            f"obsadę ({horizon}); "
            + (
                "wspólna pula MD zamówienia pozostała bez zmian."
                if case.uses_shared_md_pool
                else f"pozostałe {format_md(remaining)} MD zostają na linii."
            )
            + (" Kontrakt wrócił do aktywnych." if contract_reopened else "")
        )
    elif payload.action == OFFBOARDING_RESOLUTION_REMOVE:
        event_type = EVENT_MD_OFFBOARDING_REMOVED
        description = f"{source_name} — zakończenie współpracy obsłużone: " + (
            "linia usunięta z aktywnej obsady; wspólna pula MD zamówienia "
            "pozostała bez zmian."
            if case.uses_shared_md_pool
            else f"pozostałe {format_md(remaining)} MD usunięto z zamówienia."
        )
    else:
        event_type = EVENT_MD_OFFBOARDING_TRANSFERRED
        description = f"{source_name} — zakończenie współpracy obsłużone: " + (
            f"wskazano {target_name}; wspólna pula MD zamówienia pozostała bez zmian."
            if case.uses_shared_md_pool
            else (
                f"pozostałe {format_md(remaining)} MD przeliczono na "
                f"{format_md(transferred_md)} MD dla {target_name} "
                f"według stawki {'osoby odchodzącej' if payload.rate_basis == OFFBOARDING_RATE_BASIS_DEPARTING else 'osoby przejmującej'}."
            )
        )
    record_event(
        db,
        group_id=group_id,
        order_id=source.id,
        event_type=event_type,
        description=description,
        payload={
            "offboarding_case_id": case.id,
            "source_order_id": source.id,
            "target_order_id": case.target_order_id,
            "rate_basis": case.rate_basis,
            **case.resolution_payload,
        },
        user_id=user.id,
    )
    await handle_offboarding_case_alerts(
        db, case_id=case.id, handled_by_user_id=user.id, now=now
    )
    await commit_order_write(db)
    await db.refresh(case)
    return _offboarding_case_to_read(
        case,
        with_finance=await _can_see_finance(db, user, client_id),
    )


@router.post(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}/swap",
    response_model=OrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
async def swap_consultant(
    client_id: int,
    group_id: int,
    line_id: int,
    payload: OrderLineSwapRequest,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Zamiana kontraktora — nowa linia z MD przeliczonymi na nową stawkę.

    Przeliczenie zachowuje wartość zamówienia w PLN:
    ``md_nowe × stawka_nowa == md_pozostałe × stawka_stara``.

    Zamiana działa OD DNIA ZAMIANY W PRZÓD. MD zaraportowane wcześniej
    rozlicza się stawką poprzednika, więc wpisy konsumpcji sprzed tej daty
    zostają nietknięte, a obie stawki i obie liczby MD lądują w historii —
    bez nich nie da się rozliczyć faktury za miesiąc zamiany.
    """
    await _assert_line_finance_write_allowed(
        db, user, client_id, {"rate_cost", "rate_revenue"}
    )
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    old = await db.scalar(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract).selectinload(Contract.candidate))
        .where(
            ClientOrder.id == line_id,
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
        .with_for_update()
    )
    if old is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")
    await _assert_no_pending_offboarding_case(db, group_id=group.id, order_id=old.id)
    # Zamówienie KOSZTOWE nie ma budżetu per linia — pula mieszka na grupie,
    # a linia z definicji ma `md_total = None` (`_build_line`). Warunek pisany
    # pod tryb MD odrzucał więc KAŻDĄ zamianę u klienta kosztowego, i to
    # komunikatem o brakującym budżecie, czyli sugerującym dane do uzupełnienia
    # w stanie, którego nie da się usunąć. Tu nie ma czego przenosić: budżet
    # zostaje na grupie, a rozliczenie i tak liczy się od zera z faktur
    # (`settle_group` nie filtruje po statusie linii, więc domknięcie
    # poprzednika nie odsłania wydanych już pieniędzy).
    is_cost = bool(group.is_cost_based)
    is_shared_md = uses_shared_md_pool(group)
    has_group_budget = is_cost or is_shared_md
    if has_group_budget:
        if old.md_rate_revenue is None:
            raise HTTPException(
                422, detail="Linia nie ma stawki przychodowej do przeniesienia"
            )
    elif old.md_total is None or old.md_rate_revenue is None:
        raise HTTPException(422, detail="Linia nie ma budżetu MD do przeniesienia")
    if old.status != ClientOrderStatus.active:
        raise HTTPException(
            422, detail="Zamienić można tylko aktywną linię konsultanta"
        )
    if old.start_date and payload.swap_date < old.start_date:
        raise HTTPException(
            422, detail="Data zamiany jest wcześniejsza niż start linii"
        )

    md_remaining_old: Optional[Decimal] = None
    md_total_new: Optional[Decimal] = None
    if not has_group_budget:
        await recompute_remaining(db, old)
        md_remaining_old = Decimal(str(old.md_remaining or 0))
        try:
            md_total_new = swap_md_total(
                md_remaining_old=md_remaining_old,
                rate_revenue_old=old.md_rate_revenue,
                rate_revenue_new=payload.rate_revenue,
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc

    new_contract = await _resolve_contract(db, client_id, payload.contract_id)

    # Domknięcie starej linii lustrzane wobec syncu terminacji kontraktu
    # (`contracts.py`): data zawsze, status `completed` dopiero gdy dzień
    # zamiany nadszedł. Zamiana zaplanowana na przyszłość nie może wyłączyć
    # konsultanta, który jeszcze pracuje. Lustro jest pełne dopiero przy
    # `business_today()`: `contracts.py` liczy tę granicę dniem biznesowym, więc
    # `date.today()` rozjeżdżałby oba mechanizmy o dobę między 22:00 UTC
    # a północą — zamiana „na dziś" zostawiałaby poprzednika jako `active`.
    today = business_today()
    # Zapamiętane PRZED nadpisaniem — nowa linia dziedziczy planowany koniec
    # zaangażowania po poprzedniku. Odczyt po przypisaniu dałby zawsze
    # `payload.swap_date` i po cichu skróciłby pracę następcy do jednego dnia.
    planned_end = old.end_date
    old.end_date = payload.swap_date
    if payload.swap_date <= today:
        old.status = ClientOrderStatus.completed

    old_who = consultant_display_name(old)
    new_candidate = new_contract.candidate
    new_who = (
        f"{new_candidate.name or ''} {new_candidate.lastname or ''}".strip()
        if new_candidate
        else "konsultant"
    )

    new_line = ClientOrder(
        client_id=client_id,
        contract_id=new_contract.id,
        job_id=old.job_id,
        order_group_id=group.id,
        order_type=group.order_type,
        title=f"Zamówienie {group.order_number} — {new_who}"[:255],
        status=ClientOrderStatus.active,
        start_date=payload.swap_date,
        end_date=planned_end if planned_end is not None else group.end_date,
        filled_at=datetime.now(timezone.utc),
        md_rate_cost=payload.rate_cost,
        md_rate_revenue=payload.rate_revenue,
        rate_candidate=payload.rate_cost,
        rate_client=payload.rate_revenue,
        rate_unit=RateUnit.daily,
        billing_hours_per_month=160,
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        # Tryb „md": budżet nowej linii POWSTAŁ z przeliczenia, a nie z kwoty
        # wpisanej przez operatora. Zapisanie go jako „amount" sugerowałoby
        # kwotę, której nikt nie podał.
        # Linia kosztowa: komplet NULL-i. `ck_client_orders_md_coherence`
        # dopuszcza albo pełen zestaw pól MD, albo żadnego — wpisanie tu
        # trybu „md" bez liczby wywróciłoby zapis na poziomie bazy.
        md_input_mode=None if has_group_budget else INPUT_MODE_MD,
        md_input_value=md_total_new,
        md_total=md_total_new,
        md_remaining=md_total_new,
        md_manual_adjustment=Decimal("0"),
        predecessor_order_id=old.id,
        created_by_user_id=user.id,
    )
    db.add(new_line)
    await db.flush()
    await _sync_contract_after_live_group_line(db, new_line, actor_id=user.id)

    event_payload: dict[str, object] = {
        "swap_date": payload.swap_date.isoformat(),
        "old_order_id": old.id,
        "old_consultant": old_who,
        # `str(None)` zapisałoby do dziennika literał "None" — wartość, która
        # w rozliczeniu faktury czyta się jak stawka, a nie jak jej brak.
        # `rate_cost` jest wymagane w schemacie, więc to nie powinno zajść;
        # dziennik jednak przeżywa dane starsze od walidacji.
        "old_rate_cost": None if old.md_rate_cost is None else str(old.md_rate_cost),
        "old_rate_revenue": str(old.md_rate_revenue),
        "new_order_id": new_line.id,
        "new_consultant": new_who,
        "new_rate_cost": str(payload.rate_cost),
        "new_rate_revenue": str(payload.rate_revenue),
        "cost_based": is_cost,
        "md_budget_based": is_shared_md,
    }
    if is_cost:
        # Zamówienie kosztowe: żadnej arytmetyki MD. Pula jest wspólna i została
        # rozliczona fakturami, więc jedyne, co się zmienia od dnia zamiany, to
        # osoba i jej stawki. Wypisanie tu „pozostało — MD" mówiłoby o polu,
        # którego ta linia nigdy nie miała.
        description = (
            f"Zamiana kontraktora {payload.swap_date.isoformat()} "
            f"(zamówienie kosztowe): "
            f"{old_who} ({format_md(old.md_rate_revenue)} zł/MD) → "
            f"{new_who} ({format_md(payload.rate_revenue)} zł/MD). "
            f"Kwota zamówienia zostaje wspólna dla całej grupy."
        )
    elif is_shared_md:
        description = (
            f"Zamiana kontraktora {payload.swap_date.isoformat()} "
            f"(zamówienie ze wspólną pulą MD): "
            f"{old_who} ({format_md(old.md_rate_revenue)} zł/MD) → "
            f"{new_who} ({format_md(payload.rate_revenue)} zł/MD). "
            f"Budżet MD zostaje wspólny dla całej grupy."
        )
    else:
        value_pln = remaining_value_pln(
            md_remaining=md_remaining_old, rate_revenue=old.md_rate_revenue
        )
        description = (
            f"Zamiana kontraktora {payload.swap_date.isoformat()}: "
            f"{old_who} ({format_md(old.md_rate_revenue)} zł/MD, "
            f"pozostało {format_md(md_remaining_old)} MD) → "
            f"{new_who} ({format_md(payload.rate_revenue)} zł/MD, "
            f"{format_md(md_total_new)} MD). "
            f"Wartość pozostała bez zmian: {format_md(value_pln)} zł."
        )
        event_payload["old_md_remaining"] = str(md_remaining_old)
        event_payload["new_md_total"] = str(md_total_new)
        event_payload["remaining_value_pln"] = str(value_pln)
    record_event(
        db,
        group_id=group.id,
        order_id=new_line.id,
        event_type=EVENT_CONSULTANT_SWAPPED,
        description=description,
        payload=event_payload,
        user_id=user.id,
    )
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_line_swapped",
            details={"group_id": group.id, "from": old.id, "to": new_line.id},
        )
    )
    superseded_paths = await _sync_group_pdf_for_new_line(db, group=group, user=user)
    await commit_order_write(db)
    for path in superseded_paths:
        storage_service.delete_contract_document(path)

    refreshed = await db.scalar(
        select(ClientOrder)
        .options(
            selectinload(ClientOrder.contract).selectinload(Contract.candidate),
            selectinload(ClientOrder.predecessor)
            .selectinload(ClientOrder.contract)
            .selectinload(Contract.candidate),
        )
        .where(ClientOrder.id == new_line.id)
    )
    return _line_to_read(
        refreshed,
        with_finance=await _can_see_finance(db, user, client_id),
    )
