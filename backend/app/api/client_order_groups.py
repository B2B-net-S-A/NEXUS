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

Obsadę zamówienia prowadzi **delivery**: stawki linii MD ustawia admin albo
Delivery Lead przypisany do klienta (``_has_md_line_management_role``). To
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
from app.api.deps import DlAssignedOrAdmin, require_roles
from app.core.database import get_db
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
)
from app.models.md_consumption import (
    ClientOrderInvoiceConsumption,
    ClientOrderMdConsumption,
    MdConsumptionImport,
)
from app.models.contract import Contract, ContractStatus
from app.models.contract_document import ContractDocument, ContractDocumentType
from app.models.job import Job
from app.models.user import User, UserRole
from app.schemas.client_order_group import (
    ConsultantOptionRead,
    ConsultantOptionsResponse,
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
    OrderLineRead,
    OrderLineSwapRequest,
    OrderLineUpdate,
)
from app.services.client_order_lines import (
    CLIENT_CONTRACT_STATUSES,
    _line_query,
    consultant_display_name,
    lines_for_group,
    list_consultant_options,
    record_event,
    recompute_remaining,
)
from app.services.client_access import deny, resolve_client_access
from app.services.candidate_identity_quarantine import normalize_person_name_part
from app.services.cost_orders import (
    assert_cost_order_client,
    quantize_money,
    settle_group,
)
from app.services.dl_alerts import emit_cost_order_exhausted
from app.services.multi_consultant_orders import (
    EVENT_BUDGET_EXHAUSTED,
    EVENT_CONSULTANT_ADDED,
    EVENT_CONSULTANT_SWAPPED,
    EVENT_MANUAL_EDIT,
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
from app.services.order_excel_export import (
    OrderExportRow,
    build_orders_workbook,
    orders_export_filename,
)
from app.services import storage_service

router = APIRouter()

MAX_GROUP_PDF_BYTES = 25 * 1024 * 1024


# Pola pieniężne linii. Nazwy są WŁASNE, nie z `_ORDER_FINANCE_WRITE_FIELDS`
# w `client_orders.py` — tamten zbiór opisuje `rate_client`/`rate_candidate`,
# czyli stawki interpretowane przez `Contract.rate_unit`. Tutaj stawki są
# per MD i mają osobne kolumny, więc muszą mieć też własną bramkę; użycie
# tamtego zbioru przepuściłoby te pola bez żadnej kontroli.
_LINE_FINANCE_FIELDS = frozenset({"rate_cost", "rate_revenue"})


# ── Helpers ─────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    return client


async def _require_group_read(db: AsyncSession, user: User, client_id: int) -> None:
    """Ta sama decyzja dostępu co przy zamówieniach jednoosobowych.

    Lustro ``client_orders._require_client_order_read``: linia niesie kandydata
    i stawki, więc wymaga jawnego przypisania DL/TAC, a nie samej roli.
    """
    await _assert_client(db, client_id)
    # Head of Recruitment i Finanse mają prawo do akcji cyklu życia (patrz
    # `_ORDER_LIFECYCLE_ROLES`), więc muszą też WIDZIEĆ zamówienia — inaczej
    # dostają uprawnienie do przycisku, którego nigdy nie zobaczą. Poszerzenie
    # jest wąskie: dotyczy TEJ powierzchni, nie reszty profilu klienta.
    if user.has_any_role(UserRole.head_of_recruitment, UserRole.finance):
        return
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają jawnego przypisania DL/TAC")


def _assert_multi_client(client_id: int) -> None:
    if not is_multi_consultant_client(client_id):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Ten klient nie jest rozliczany w modelu wielo-konsultantowym. "
                "Użyj zwykłego zamówienia albo dopisz klienta do "
                "MULTI_CONSULTANT_ORDER_CLIENT_IDS."
            ),
        )


def _has_md_line_management_role(user: User) -> bool:
    """Czy ROLA użytkownika prowadzi linie MD: admin albo Delivery Lead.

    **Nazwa mówi „rola" celowo — ta funkcja NIE sprawdza klienta.** Zawężenie do
    klienta, do którego DL jest przypisany, robi ``DlAssignedOrAdmin`` na trasie
    (zapis) i ``_require_group_read`` (odczyt). Nowy endpoint, który zawoła
    poniższe guardy z pominięciem tamtych, dałby każdemu DL stawki wszystkich
    klientów — i nic tutaj by tego nie zatrzymało.

    Delivery jest tu CELOWO, mimo że nie ma ``VIEW_FINANCE``: to delivery układa
    obsadę zamówienia i negocjuje stawki per konsultant, a wymóg admina do
    dodania konsultanta czynił tę zakładkę bezużyteczną dla osób, które
    faktycznie ją obsługują.

    Zakres jest wąski i tego trzeba pilnować:

    * tylko kolumny ``md_rate_cost`` / ``md_rate_revenue`` na TEJ powierzchni —
      legacy ``rate_client`` / ``rate_candidate`` / ``total_value`` w module
      zamówień zostają admin-only (``_ORDER_FINANCE_WRITE_FIELDS``),
    * tylko klient, do którego DL jest jawnie przypisany — pilnuje tego
      ``DlAssignedOrAdmin`` na trasie, a ``_require_group_read`` na odczycie,
    * **head_of_recruitment NIE** — przechodzi przez ``DlAssignedOrAdmin``
      globalnie, bez przypisania, a przy powierzchniach finansowych repo
      konsekwentnie trzyma go poza (patrz `/settings/clients-overview`),
    * rola ``finance`` NIE — nie z powodu danych osobowych (od 19.08 finance
      ma pełny dostęp operacyjny), tylko dlatego, że stawki linii MD to tier
      ZARZĄDCZY obsady — jak wyżej, poza nim stoi też recruiter i HoR.

    Uprawnienie do ODCZYTU i ZAPISU jest wyliczane z tej jednej funkcji.
    Rozdzielenie ich dałoby rolę, która zapisuje stawkę i widzi w jej miejscu
    „—" — czyli formularz, w którym nie da się sprawdzić własnej pracy.
    """
    # Sam test roli. Przypisanie do klienta MUSI być sprawdzone przez trasę.
    return user.has_any_role(UserRole.admin, UserRole.delivery_lead)


# Role uprawnione do CYKLU ŻYCIA zamówienia (usuń / zakończ / przywróć /
# przedłuż). Świadomie SZERSZE niż `_has_md_line_management_role`, który
# rządzi stawkami i zostaje przy admin + Delivery Lead.
#
# Ticket wymienia je przez wykluczenie: „wszystkie role oprócz Sourcer,
# Rekruter, TAC, Talent Community". Roli „Talent Community" w systemie nie ma;
# deprecated `user` (read-only viewer) jest poza z tego samego powodu co tamte
# trzy. Zostają więc admin, Head of Recruitment, Delivery Lead i Finanse.
#
# Konsekwencja do wiedzenia: `head_of_recruitment` przechodzi guardy tras
# GLOBALNIE, bez przypisania do klienta — dostaje te akcje u wszystkich
# klientów. (Dawna uwaga o odcięciu `finance` od powierzchni kandydackich
# nieaktualna — od 19.08 finance ma pełny dostęp operacyjny.)
_ORDER_LIFECYCLE_ROLES = (
    UserRole.admin,
    UserRole.head_of_recruitment,
    UserRole.delivery_lead,
    UserRole.finance,
)


#: Zależność tras cyklu życia. Sam test roli — przypisanie do klienta
#: dokłada `_require_order_lifecycle` w ciele handlera, bo zna `client_id`.
OrderLifecycleUser = Annotated[User, Depends(require_roles(*_ORDER_LIFECYCLE_ROLES))]

#: Zależność ODCZYTU zamówień. `TacPlus` tu nie wystarcza: odrzuca Head of
#: Recruitment i Finanse, którym ticket przyznaje akcje cyklu życia — a rola,
#: która może zamówienie zakończyć, ale nie może go zobaczyć, dostaje przycisk
#: bez ekranu. Zawężenie do konkretnego klienta robi `_require_group_read`.
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


def _has_order_lifecycle_role(user: User) -> bool:
    """Sam test ROLI — przypisanie do klienta sprawdza `_require_order_lifecycle`."""
    return user.has_any_role(*_ORDER_LIFECYCLE_ROLES)


async def _require_order_lifecycle(
    db: AsyncSession, user: User, client_id: int
) -> None:
    """Bramka czterech akcji cyklu życia zamówienia.

    NIE reużywa `DlAssignedOrAdmin`, bo tamta odrzuca rolę Finanse, a ticket
    wprost jej te akcje przyznaje. Delivery Lead nadal potrzebuje jawnego
    przypisania do klienta — bez tego każdy DL kasowałby zamówienia wszystkich
    klientów, czego żadna wersja ticketu nie żąda.
    """
    await _assert_client(db, client_id)
    if not _has_order_lifecycle_role(user):
        raise deny("ta akcja wymaga roli zarządzającej zamówieniami")
    if user.has_any_role(
        UserRole.admin, UserRole.head_of_recruitment, UserRole.finance
    ):
        return
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają jawnego przypisania DL")


def _assert_line_finance_write_allowed(user: User, supplied: set[str]) -> None:
    """Stawki linii MD pisze admin albo przypisany Delivery Lead."""
    forbidden = sorted(supplied & _LINE_FINANCE_FIELDS)
    if forbidden and not _has_md_line_management_role(user):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            detail={"code": "finance_fields_forbidden", "fields": forbidden},
        )


def _can_see_finance(user: User) -> bool:
    """Stawki linii MD widzi ten, kto może je ustawiać, oraz role z VIEW_FINANCE.

    TAC zostaje przy redakcji: jest w zespole klienta i widzi konsultantów oraz
    zużycie MD, ale nie prowadzi obsady zamówienia, więc stawki go nie dotyczą.
    """
    return _has_md_line_management_role(user) or user_has_capability(
        user, AnalyticsCapability.VIEW_FINANCE
    )


def _initial_group_status(start_date: date) -> str:
    return GROUP_STATUS_SCHEDULED if start_date > date.today() else GROUP_STATUS_ACTIVE


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
    return group


def _line_to_read(
    order: ClientOrder,
    *,
    with_finance: bool,
    invoiced: Optional[Decimal] = None,
    unsettled: Optional[Decimal] = None,
    missing_month: Optional[str] = None,
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
    )


async def _group_to_read(
    db: AsyncSession, group: ClientOrderGroup, *, with_finance: bool
) -> OrderGroupRead:
    lines = await lines_for_group(db, group.id)
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

    event_count = await db.scalar(
        select(func.count(ClientOrderGroupEvent.id)).where(
            ClientOrderGroupEvent.group_id == group.id
        )
    )

    budget_used: Optional[Decimal] = None
    if group.is_cost_based and group.budget_amount is not None:
        pool = quantize_money(group.budget_amount) + quantize_money(
            group.budget_manual_adjustment or 0
        )
        remaining = quantize_money(group.budget_remaining or 0)
        budget_used = quantize_money(max(Decimal("0"), pool - remaining))

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
        closure_date=group.closure_date,
        closure_reason=group.closure_reason,
        is_cost_based=group.is_cost_based,
        budget_amount=group.budget_amount if with_finance else None,
        budget_used=budget_used if with_finance else None,
        budget_remaining=group.budget_remaining if with_finance else None,
        budget_manual_adjustment=(
            group.budget_manual_adjustment
            if group.is_cost_based and with_finance
            else None
        ),
        predecessor_group_id=group.predecessor_group_id,
        filename=group.filename,
        has_file=group.file_path is not None,
        content_type=group.content_type,
        size_bytes=group.size_bytes,
        file_uploaded_at=group.file_uploaded_at,
        can_add_consultant=group.status
        in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED),
        lines=reads,
        active_consultants=sum(1 for r in reads if r.is_active),
        event_count=int(event_count or 0),
    )


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
    end_date: Optional[date],
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
        end_date=end_date,
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
    # Daty szkicu kontraktu są LUSTREM dat linii (a przy pustym końcu linii —
    # końca całego zamówienia), bo tylko tyle wiadomo: formularz obsady nie
    # pyta o okres umowy. Kto będzie ten kontrakt aktywował, MUSI je świadomie
    # potwierdzić — to nie są daty przepisane z dokumentu, tylko z zamówienia,
    # pod które osoba została dopisana.
    return await _contract_for_candidate(
        db,
        client_id=group.client_id,
        candidate_id=payload.candidate_id,  # type: ignore[arg-type]
        start_date=payload.start_date,
        end_date=payload.end_date or group.end_date,
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
    if group.is_cost_based:
        if payload.input_mode is not None or payload.input_value is not None:
            raise HTTPException(
                422,
                detail=(
                    "Zamówienie kosztowe ma wspólną kwotę — nie podawaj "
                    "budżetu MD przy konsultancie"
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
        if group.status == GROUP_STATUS_SCHEDULED
        else ClientOrderStatus.active
    )
    line = ClientOrder(
        client_id=group.client_id,
        contract_id=contract.id,
        job_id=payload.job_id,
        order_group_id=group.id,
        title=f"Zamówienie {group.order_number} — {who or 'konsultant'}"[:255],
        status=line_status,
        start_date=payload.start_date,
        end_date=payload.end_date or group.end_date,
        filled_at=now if line_status == ClientOrderStatus.active else None,
        md_rate_cost=payload.rate_cost,
        md_rate_revenue=payload.rate_revenue,
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


def _describe_line(
    order: ClientOrder, who: str, *, contract_created: bool = False
) -> str:
    # Fakt założenia kontraktu ląduje w opisie zdarzenia, a nie tylko w polach
    # linii: historia zamówienia jest jedynym miejscem, w którym widać, że ta
    # osoba weszła spoza rekrutacji u tego klienta i ma u niego świeży szkic
    # umowy do domknięcia.
    suffix = (
        " (osoba z bazy Nexus — założono szkic kontraktu)" if contract_created else ""
    )
    if order.md_total is None:
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
    user: OrderGroupReader,
    db: AsyncSession = Depends(get_db),
):
    """Zamówienia klienta wraz z liniami konsultantów.

    Klient spoza listy dostaje PUSTĄ listę, nie 403 — front pyta o ten zasób
    dopiero po sprawdzeniu flagi, a odmowa renderowałaby się jako awaria tam,
    gdzie faktycznie po prostu nie ma czego pokazać.
    """
    await _require_group_read(db, user, client_id)
    if not is_multi_consultant_client(client_id):
        return OrderGroupListResponse(groups=[], total_groups=0, total_consultants=0)

    # Scanner materializuje przejścia codziennie, ale odczyt jest dodatkową
    # idempotentną bramą: zamówienie zaczynające się dziś ma stać się bieżące
    # przy pierwszym wejściu użytkownika, nawet jeśli pętla dobowa jeszcze nie
    # zdążyła wykonać iteracji.
    if await materialize_scheduled_order_groups(db, client_id=client_id):
        await db.commit()

    result = await db.execute(
        select(ClientOrderGroup)
        .where(ClientOrderGroup.client_id == client_id)
        .order_by(ClientOrderGroup.created_at.desc(), ClientOrderGroup.id.desc())
    )
    with_finance = _can_see_finance(user)
    models = list(result.scalars())
    reads_by_id = {
        group.id: await _group_to_read(db, group, with_finance=with_finance)
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
    return OrderGroupListResponse(
        groups=groups,
        total_groups=len(models),
        total_consultants=sum(read.active_consultants for read in reads_by_id.values()),
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

    rows: list[OrderExportRow] = []
    for group_id in requested:
        group = await _group_to_read(
            db, by_id[group_id], with_finance=_can_see_finance(user)
        )
        if not group.lines:
            rows.append(
                OrderExportRow(
                    consultant_name="",
                    order_number=group.order_number,
                    cost_rate=None,
                    revenue_rate=None,
                    start_date=group.start_date,
                    end_date=group.end_date,
                    allocation=group.budget_amount if group.is_cost_based else None,
                    consumption=None,
                )
            )
            continue
        for line in group.lines:
            consumption: Optional[Decimal]
            if group.is_cost_based:
                consumption = line.invoiced_total
            elif line.md_total is None:
                consumption = None
            else:
                consumption = (
                    line.md_total
                    + (line.md_manual_adjustment or Decimal("0"))
                    - (line.md_remaining or Decimal("0"))
                )
            rows.append(
                OrderExportRow(
                    consultant_name=line.consultant_name,
                    order_number=group.order_number,
                    cost_rate=line.rate_cost,
                    revenue_rate=line.rate_revenue,
                    start_date=group.start_date,
                    end_date=group.end_date,
                    allocation=(
                        group.budget_amount if group.is_cost_based else line.md_total
                    ),
                    consumption=consumption,
                )
            )

    content = await run_in_threadpool(
        build_orders_workbook, rows, include_model_columns=True
    )
    filename = orders_export_filename(client.display_name or client.name)
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
    user: DlAssignedOrAdmin,
    q: str = Query("", max_length=120, description="Imię i nazwisko"),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    """Kogo można dołożyć do zamówienia — jedna lista, dwa źródła.

    Osoby z kontraktem u tego klienta ORAZ pozostali aktywni konsultanci z bazy
    Nexus, scaleni, bez duplikatów i posortowani alfabetycznie po imieniu.
    Każda pozycja niesie etykietę pochodzenia, bo wybór między dwiema osobami
    o tym samym nazwisku bywa wyborem między „ta, którą tu znamy" a „ta z bazy".

    Bramka zapisu (``DlAssignedOrAdmin``), a nie odczytu: ta lista istnieje
    wyłącznie po to, żeby nakarmić ``add_line``. Kto nie może dodać linii, nie
    potrzebuje nazwisk konsultantów z całej bazy.

    Klient spoza listy wielo-konsultantowej dostaje PUSTĄ listę, nie 422 — to
    GET, a odmowa renderuje się w interfejsie jak awaria.
    """
    await _assert_client(db, client_id)
    if not is_multi_consultant_client(client_id):
        return ConsultantOptionsResponse(options=[], total=0)

    options, total = await list_consultant_options(
        db, client_id=client_id, query=q, limit=limit
    )
    include_rate_suggestions = _has_md_line_management_role(user)
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
                # Endpoint nazwisk jest dostępny także Head of Recruitment,
                # ale stawki linii prowadzą wyłącznie admin i przypisany DL.
                # Nie rozszerzamy uprawnień finansowych przy okazji autofillu.
                suggested_rate_cost=(
                    o.suggested_rate_cost if include_rate_suggestions else None
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
    user: OrderGroupReader,
    db: AsyncSession = Depends(get_db),
):
    """Historia zamówienia — chronologicznie, od najnowszego."""
    await _require_group_read(db, user, client_id)
    _assert_multi_client(client_id)
    await _load_group(db, client_id, group_id)

    result = await db.execute(
        select(ClientOrderGroupEvent)
        .where(ClientOrderGroupEvent.group_id == group_id)
        .order_by(
            ClientOrderGroupEvent.created_at.desc(), ClientOrderGroupEvent.id.desc()
        )
    )
    with_finance = _can_see_finance(user)
    events: list[OrderGroupEventRead] = []
    for ev in result.scalars():
        # `payload` niesie stawki (rozliczenie faktury w miesiącu zamiany),
        # więc dla ról bez VIEW_FINANCE znika w całości — opis po polsku
        # zostaje, bo mówi KTO i KIEDY, a nie ZA ILE.
        events.append(
            OrderGroupEventRead(
                id=ev.id,
                event_type=ev.event_type,
                event_label=EVENT_TYPE_LABELS.get(ev.event_type, ev.event_type),
                description=ev.description,
                order_id=ev.order_id,
                payload=ev.payload if with_finance else None,
                created_by_user_id=ev.created_by_user_id,
                created_at=ev.created_at,
            )
        )
    return OrderGroupEventsResponse(events=events)


@router.get("/{client_id}/order-groups/{group_id}/file")
async def download_order_group_file(
    client_id: int,
    group_id: int,
    user: OrderGroupReader,
    db: AsyncSession = Depends(get_db),
):
    """Pobierz master PDF zamówienia wielo-konsultantowego."""

    await _require_group_read(db, user, client_id)
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
    user: DlAssignedOrAdmin,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Zapisz master PDF i upsertuj jego kopię na każdym kontrakcie z grupy."""

    await _assert_client(db, client_id)
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
    await db.commit()
    if previous_master and previous_master != master_path:
        storage_service.delete_client_order_group_po(previous_master)
    for path in superseded_paths:
        storage_service.delete_contract_document(path)
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


@router.delete(
    "/{client_id}/order-groups/{group_id}/file",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_order_group_file(
    client_id: int,
    group_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Usuń master i tylko automatyczne kopie PDF z kontraktów.

    Ręczne dokumenty (``source_order_group_id IS NULL``) nie są dotykane.
    Usunięcie samej grupy korzysta z innej ścieżki i zachowuje kopie jako
    historię — tutaj operator jawnie usuwa błędny załącznik z formularza.
    """

    await _assert_client(db, client_id)
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
    await db.commit()
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
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Nowe zamówienie klienta wraz z jedną lub wieloma liniami konsultantów."""
    if payload.lines:
        _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    if payload.end_date and payload.end_date < payload.start_date:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")
    if payload.is_cost_based:
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
        status=_initial_group_status(payload.start_date),
        is_cost_based=payload.is_cost_based,
        budget_amount=payload.budget_amount,
        # Startowa reszta = pełna kwota. Zamówienie kosztowe bez tej wartości
        # naruszyłoby CHECK spójności już przy INSERT-cie.
        budget_remaining=payload.budget_amount,
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
        record_event(
            db,
            group_id=group.id,
            order_id=line.id,
            event_type=EVENT_CONSULTANT_ADDED,
            description=_describe_line(line, who, contract_created=contract_created),
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
            details={"group_id": group.id, "lines": len(payload.lines)},
        )
    )
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


@router.patch("/{client_id}/order-groups/{group_id}", response_model=OrderGroupRead)
async def update_order_group(
    client_id: int,
    group_id: int,
    payload: OrderGroupUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja numeru i okresu zamówienia (bez dotykania linii)."""
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    data = payload.model_dump(exclude_unset=True)
    if not data:
        return await _group_to_read(db, group, with_finance=_can_see_finance(user))

    new_start = data.get("start_date", group.start_date)
    new_end = data.get("end_date", group.end_date)
    if new_end and new_start and new_end < new_start:
        raise HTTPException(422, detail="Data zakończenia jest wcześniejsza niż start")

    budget_fields = {"budget_amount", "budget_manual_adjustment"}
    if data.keys() & budget_fields and not group.is_cost_based:
        raise HTTPException(
            422,
            detail="Kwotę zamówienia można zmieniać tylko na zamówieniu kosztowym",
        )
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

    if data.keys() & budget_fields:
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
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


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

    lines = await lines_for_group(db, group.id)
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
    await db.commit()
    # Automatyczne kopie na kontraktach są osobnymi plikami i pozostają jako
    # zapis historyczny (FK źródła przechodzi na NULL). Master należący do
    # usuniętej grupy nie ma już konsumenta, więc można go bezpiecznie zwolnić.
    if master_path:
        storage_service.delete_client_order_group_po(master_path)


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
        select(ClientOrder).where(
            ClientOrder.id == line_id, ClientOrder.order_group_id == group.id
        )
    )
    if line is None:
        raise HTTPException(404, detail="Ta linia nie należy do tego zamówienia")

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
    await db.commit()


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

    today = date.today()
    group.status = GROUP_STATUS_COMPLETED
    group.closure_date = payload.closure_date
    group.closure_reason = (payload.closure_reason or "").strip() or None
    group.closed_at = datetime.now(timezone.utc)
    group.closed_by_user_id = user.id
    if group.end_date is None or group.end_date > payload.closure_date:
        group.end_date = payload.closure_date

    closed_lines = 0
    for line in await lines_for_group(db, group.id):
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
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


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
    przyjmie.
    """
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)

    if group.status == GROUP_STATUS_ACTIVE:
        raise HTTPException(409, detail="To zamówienie jest już aktywne")
    if group.status == GROUP_STATUS_EXHAUSTED:
        raise HTTPException(
            409,
            detail=(
                "Zamówienie jest wyczerpane, nie zakończone. Skoryguj kwotę "
                "zamówienia albo załóż nowe."
            ),
        )

    previous_closure = group.closure_date
    group.status = GROUP_STATUS_ACTIVE
    group.closure_date = None
    group.closure_reason = None
    group.closed_at = None
    group.closed_by_user_id = None

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
            )
        },
        user_id=user.id,
    )
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


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
    if payload.lines:
        _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _require_order_lifecycle(db, user, client_id)
    _assert_multi_client(client_id)
    source = await _load_group(db, client_id, group_id)

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

    group = ClientOrderGroup(
        client_id=client_id,
        order_number=payload.order_number.strip(),
        start_date=payload.start_date,
        end_date=payload.end_date,
        notes=payload.notes,
        # Każde przedłużenie zaczyna jako zaplanowane. Jeśli data już nadeszła,
        # wspólny materializer poniżej od razu aktywuje je i zamknie poprzednika.
        status=GROUP_STATUS_SCHEDULED,
        is_cost_based=source.is_cost_based,
        budget_amount=payload.budget_amount,
        budget_remaining=payload.budget_amount,
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
            description=_describe_line(line, who, contract_created=contract_created),
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
    await db.commit()
    await db.refresh(group)
    return await _group_to_read(db, group, with_finance=_can_see_finance(user))


@router.post(
    "/{client_id}/order-groups/{group_id}/lines",
    response_model=OrderLineRead,
    status_code=status.HTTP_201_CREATED,
)
async def add_line(
    client_id: int,
    group_id: int,
    payload: OrderLineCreate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Dodaje konsultanta do istniejącego zamówienia."""
    _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    group = await _load_group(db, client_id, group_id)
    # Wyczerpane/zakończone zamówienie nie przyjmuje nowych konsultantów.
    # Zaplanowane przyjmuje — model wieloosobowy zakłada, że obsada może być
    # kompletowana już po utworzeniu zamówienia, jeszcze przed jego startem.
    # 409, nie 422: żądanie jest poprawne, to STAN ŚWIATA go odrzuca — i to
    # ten stan trzeba zmienić gdzie indziej (nowe zamówienie albo korekta
    # kwoty), a nie treść żądania.
    if group.status not in (GROUP_STATUS_ACTIVE, GROUP_STATUS_SCHEDULED):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=(
                f"Zamówienie {group.order_number} jest "
                f"{GROUP_STATUS_LABELS.get(group.status, group.status).lower()} — "
                "nie można dodać do niego konsultanta."
            ),
        )

    line, who, contract_created = await _build_line(
        db, group=group, payload=payload, user=user
    )
    await db.flush()
    record_event(
        db,
        group_id=group.id,
        order_id=line.id,
        event_type=EVENT_CONSULTANT_ADDED,
        description=_describe_line(line, who, contract_created=contract_created),
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
    await db.commit()
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
    return _line_to_read(refreshed, with_finance=_can_see_finance(user))


@router.patch(
    "/{client_id}/order-groups/{group_id}/lines/{line_id}",
    response_model=OrderLineRead,
)
async def update_line(
    client_id: int,
    group_id: int,
    line_id: int,
    payload: OrderLineUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Edycja linii: stawki, budżet albo ręczna korekta pozostałych MD."""
    supplied = payload.model_fields_set
    _assert_line_finance_write_allowed(user, set(supplied))
    await _assert_client(db, client_id)
    _assert_multi_client(client_id)
    await _load_group(db, client_id, group_id)

    # `_line_query()` (kanoniczny komplet loaderów), bo płaski
    # `selectinload(predecessor)` ładował samego poprzednika, a `_line_to_read`
    # schodzi z niego na `contract.candidate` (`predecessor_consultant_name`).
    # W async SQLAlchemy to leniwe doczytanie leci `MissingGreenlet` → 500 bez
    # nagłówków CORS, czyli „Network Error" w przeglądarce. Trafiało w KAŻDĄ
    # edycję linii po zamianie kontraktora, i to już PO `commit()` — zmiana
    # zapisywała się, a operator widział błąd bez treści i ponawiał.
    line = await db.scalar(
        _line_query().where(
            ClientOrder.id == line_id,
            ClientOrder.order_group_id == group_id,
            ClientOrder.client_id == client_id,
        )
    )
    if line is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")

    data = payload.model_dump(exclude_unset=True)
    changed: list[str] = []

    if "rate_cost" in data:
        line.md_rate_cost = data["rate_cost"]
        changed.append("stawka kosztowa")
    if "end_date" in data:
        line.end_date = data["end_date"]
        changed.append("data zakończenia")

    # Stawka przychodowa i budżet przeliczają md_total razem — zmiana samej
    # stawki przy trybie „kwota" musi zmienić liczbę MD, inaczej zamówienie
    # zaczęłoby opiewać na inną kwotę, niż podpisano.
    recompute_total = (
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
                + f". Pozostało {format_md(line.md_remaining)} MD."
            ),
            payload={"changed": changed, "md_remaining": str(line.md_remaining)},
            user_id=user.id,
        )
    await db.commit()
    await db.refresh(line)
    return _line_to_read(line, with_finance=_can_see_finance(user))


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
    user: DlAssignedOrAdmin,
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
    _assert_line_finance_write_allowed(user, {"rate_cost", "rate_revenue"})
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
    )
    if old is None:
        raise HTTPException(404, detail="Linia nie istnieje w tym zamówieniu")
    # Zamówienie KOSZTOWE nie ma budżetu per linia — pula mieszka na grupie,
    # a linia z definicji ma `md_total = None` (`_build_line`). Warunek pisany
    # pod tryb MD odrzucał więc KAŻDĄ zamianę u klienta kosztowego, i to
    # komunikatem o brakującym budżecie, czyli sugerującym dane do uzupełnienia
    # w stanie, którego nie da się usunąć. Tu nie ma czego przenosić: budżet
    # zostaje na grupie, a rozliczenie i tak liczy się od zera z faktur
    # (`settle_group` nie filtruje po statusie linii, więc domknięcie
    # poprzednika nie odsłania wydanych już pieniędzy).
    is_cost = bool(group.is_cost_based)
    if is_cost:
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
    if not is_cost:
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
    # konsultanta, który jeszcze pracuje.
    today = date.today()
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
        title=f"Zamówienie {group.order_number} — {new_who}"[:255],
        status=ClientOrderStatus.active,
        start_date=payload.swap_date,
        end_date=planned_end if planned_end is not None else group.end_date,
        filled_at=datetime.now(timezone.utc),
        md_rate_cost=payload.rate_cost,
        md_rate_revenue=payload.rate_revenue,
        # Tryb „md": budżet nowej linii POWSTAŁ z przeliczenia, a nie z kwoty
        # wpisanej przez operatora. Zapisanie go jako „amount" sugerowałoby
        # kwotę, której nikt nie podał.
        # Linia kosztowa: komplet NULL-i. `ck_client_orders_md_coherence`
        # dopuszcza albo pełen zestaw pól MD, albo żadnego — wpisanie tu
        # trybu „md" bez liczby wywróciłoby zapis na poziomie bazy.
        md_input_mode=None if is_cost else INPUT_MODE_MD,
        md_input_value=md_total_new,
        md_total=md_total_new,
        md_remaining=md_total_new,
        md_manual_adjustment=Decimal("0"),
        predecessor_order_id=old.id,
        created_by_user_id=user.id,
    )
    db.add(new_line)
    await db.flush()

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
    await db.commit()
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
    return _line_to_read(refreshed, with_finance=_can_see_finance(user))
