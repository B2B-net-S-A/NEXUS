"""Router `/api/clients/{client_id}/orders` + `/contract-with-order` + `/contracts-with-orders`.

Refactor 2026-05-11 (Order:Contract M:N → 1:N):
- Order ZAWSZE pod konkretnym kandydackim Contract
- 1 Contract ma N Orderów w czasie (przedłużenia)
- Grouped response: lista kontraktorów (per Contract) z timeline orderów

Flow A — "Dodaj przedłużenie" (POST /orders) — wymaga contract_id.
Flow B — "Nowy kontraktor / zamówienie" (POST /contract-with-order) —
  atomic create Contract + Order.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Annotated, Optional

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Response,
    UploadFile,
    status,
)
from fastapi.responses import FileResponse
from sqlalchemy import and_, exists, inspect, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.contracts import (
    _normalize_contract_currency,
    _raise_currency_conflict,
)
from app.api.deps import DeliveryLeadOrAdmin, require_roles
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.services.contract_lifecycle import sync_contract_to_live_order
from app.services.order_engagement_separation import assert_no_open_md_group_line
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup
from app.models.client_order_offboarding import (
    OFFBOARDING_STATUS_PENDING,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.job import Job
from app.models.order_type import OrderType
from app.models.user import User, UserRole
from app.schemas.client_order import (
    ClientOrderClose,
    ClientOrderDefaultRateUnit,
    ClientOrderExportRequest,
    ClientOrderRead,
    ClientOrdersGroupedResponse,
    ClientOrderUpdate,
    ContractWithOrdersRead,
    OrderDocumentItem,
    OrderDocumentsResponse,
    OrderExtractionResult,
)
from app.schemas.new_contractor_order import (
    NewContractorOrderRequest,
    NewContractorOrderResponse,
)
from app.services import storage_service
from app.services.ai_quota import AIQuotaExceeded, ai_feature
from app.services.client_access import deny, resolve_client_access
from app.services.client_default_rate_unit import default_rate_unit_for_client
from app.services.client_identity import client_display_name
from app.services.client_order_lines import LIVE_CONTRACT_STATUSES, recompute_remaining
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.ezdrowie import validate_project_part
from app.services.multi_consultant_orders import (
    INPUT_MODE_MD,
    quantize_md,
)
from app.services.order_group_materializer import (
    materialize_group_for_activated_order,
    md_rate_from_order_rate,
)
from app.services.order_rate_snapshots import convert_order_rate
from app.services.order_types import (
    assert_order_type_allowed,
    effective_standalone_order_type,
    should_process_active_standalone_order,
)
from app.services.cv_text_extractor import UnsupportedCvFormat, extract_text
from app.services.order_write_errors import commit_order_write
from app.services.order_pdf_parser import (
    enforce_consultant_policy_safety,
    parse_order_document,
)
from app.services.order_policies import (
    PolicyContext,
    active_policies,
    apply_policies,
    apply_rate_kind,
    is_client_in_policy,
    parse_plan,
    prepare_document_text,
    prepare_parser_text,
)
from app.services.order_excel_export import (
    OrderExportRow,
    build_orders_workbook,
    export_rows_for_group,
    is_current_order_period,
    order_type_export_label,
    orders_export_filename,
)

router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


# The combined export can contain group cards. The section gate narrows this
# legacy role alias to Admin, Finance and Delivery Lead; standalone order items
# still pass their own client-aware guards inside the handler below.
UnifiedOrderExportReader = Annotated[
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

# Structured GET responses are finance-redacted below and may be shown to TCM.
# Keep this distinct from ``UnifiedOrderExportReader``: exports and PO files are
# opaque rate-bearing artefacts and deliberately do not admit TCM.
OrderSafeReadUser = Annotated[
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


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


def _assert_allowed_order_type(client_id: int, order_type: OrderType | str) -> None:
    try:
        assert_order_type_allowed(client_id, order_type)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


# ── Helpers ────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> Client:
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if client is None:
        raise HTTPException(404, detail="Client not found")
    return client


async def _require_client_order_read(
    db: AsyncSession,
    user,
    client_id: int,
) -> None:
    """Require operational Delivery access before any order-specific guard."""

    await _assert_client(db, client_id)
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają dostępu operacyjnego Delivery")


async def _require_safe_client_order_read(
    db: AsyncSession,
    user: User,
    client_id: int,
) -> None:
    """Authorize the structured, finance-redacted Delivery order projection."""

    await _assert_client(db, client_id)
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_knowledge:
        raise deny("zamówienia klienta wymagają dostępu operacyjnego do klienta")


async def _can_read_order_file(db: AsyncSession, user: User, client_id: int) -> bool:
    """Opaque PO files keep the assigned-client finance boundary for DLs."""

    dl_assigned = await _dl_assigned_to_client(db, user, client_id)
    can_finance = _can_manage_order_finance(user, dl_assigned=dl_assigned)
    return _order_finance_visible(user, can_finance=can_finance)


async def _require_order_file_read(
    db: AsyncSession,
    user: User,
    client_id: int,
) -> None:
    await _require_client_order_read(db, user, client_id)
    if not await _can_read_order_file(db, user, client_id):
        raise deny("plik zamówienia z kwotami wymaga przypisania do klienta")


async def _read_upload_within_limit(file: UploadFile) -> bytes:
    """Wczytaj upload z twardym limitem, ZANIM cokolwiek trafi na dysk.

    Poprzednio rozmiar sprawdzany był po zapisie (`save` → `if size > MAX` →
    `delete`), więc przekroczony limit najpierw materializował plik na
    wolumenie, a sprzątanie zależało od tego, czy skasowanie się powiodło.
    Czytamy MAX+1 bajtów: nadmiar rozpoznajemy bez wciągania całości do RAM-u.
    """

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="File too large")
    return payload


#: ``client_orders.filename`` to ``VARCHAR(255)``.
_FILENAME_COLUMN_LIMIT = 255


def _fit_filename_column(filename: str) -> str:
    """Przytnij nazwę pliku do szerokości kolumny, zachowując rozszerzenie.

    Nazwa szła do bazy SUROWA, mimo że na dysk zapisywana jest już
    sanityzowana i obcięta (``storage_service._sanitize_filename``). Realna
    polska nazwa PO banku bez trudu przekracza 255 znaków, a wtedy
    ``StringDataRightTruncationError`` przy commicie jest wyjątkiem
    NIEOBSŁUŻONYM: 500 bez nagłówków CORS, czyli u użytkownika „Network
    Error" i utracony upload — mimo że plik leży już na dysku.

    Rozszerzenie zostaje na końcu, bo po nim front rozpoznaje typ pliku
    w liście dokumentów; ucinamy środek nazwy, nie ogon.
    """

    if len(filename) <= _FILENAME_COLUMN_LIMIT:
        return filename
    stem, dot, ext = filename.rpartition(".")
    if not dot or len(ext) > 16:
        # Brak rozszerzenia albo „kropka" wewnątrz zdania — nie ma czego
        # chronić, więc zwykłe obcięcie.
        return filename[:_FILENAME_COLUMN_LIMIT]
    keep = _FILENAME_COLUMN_LIMIT - len(ext) - 1
    return f"{stem[:keep]}.{ext}"


def _attach_po_bytes(
    order: ClientOrder,
    *,
    payload: bytes,
    filename: str,
    content_type: Optional[str],
    user,
) -> Optional[str]:
    """Zapisz PO na dysku i przypnij metadane do Orderu (bez commitu).

    Zwraca ścieżkę POPRZEDNIEGO pliku — wywołujący kasuje ją dopiero PO
    udanym commicie. Kasowanie tutaj oznaczało, że nieudany commit (błąd
    wstawienia Activity, zerwana sesja) zostawiał bazę wskazującą na plik,
    którego już nie ma: podgląd zamówienia zwracałby 410, a treści nie dałoby
    się odtworzyć. Kolejność „najpierw utrwal wiersz, potem zwolnij stary
    blob" zamienia najgorszy przypadek w osierocony plik na wolumenie, czyli
    coś, co da się posprzątać, zamiast bezpowrotnie utraconego dokumentu.
    """

    import io

    previous = order.file_path
    rel_path, size = storage_service.save_client_order_po(
        order_id=order.id, upload_filename=filename, source=io.BytesIO(payload)
    )
    order.filename = _fit_filename_column(filename)
    order.file_path = rel_path
    order.content_type = content_type
    order.size_bytes = size
    order.file_uploaded_by = user.id
    order.file_uploaded_at = datetime.now(timezone.utc)
    return previous if previous and previous != rel_path else None


# Bramki polityk odczytu PDF per klient. Deklaracje (env, kanoniczne ID,
# kolejność, wpływ na parser) mieszkają w ``app.services.order_policies`` —
# tu zostają wyłącznie cienkie wrappery, bo testy importują je po nazwie
# (``test_order_activation_gates_and_group_materializer``) i pinują semantykę:
# ID z env, pusta lista = fail-closed, literówka gasi jeden wpis, nie request.


def _is_nordea_order_number_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("nordea", client_id)


def _is_bank_pocztowy_order_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("bank_pocztowy", client_id)


def _is_credit_agricole_order_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("credit_agricole", client_id)


def _is_bnp_order_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("bnp", client_id)


def _is_erste_gross_rate_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("erste", client_id)


def _is_orlen_order_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("orlen", client_id)


def _is_pfron_order_client(client_id: Optional[int]) -> bool:
    return is_client_in_policy("pfron", client_id)


def _activation_candidate_rate(contract: Contract) -> Optional[Decimal]:
    """Stawka kosztowa, którą bramka aktywacji uznaje za „wypełnioną”.

    ``contract.rate_candidate`` jest kolumną CACHE: odświeża ją wyłącznie zapis
    kontraktu, a ``create_contract`` ustawia ją na ``effective_candidate_rate``
    liczone NA DZIŚ. Dla umowy ze stawką progresywną zaczynającą się w
    przyszłości (dialog rejestru buduje pierwszy krok harmonogramu na dacie
    rozpoczęcia kontraktu) kolumna zostaje więc pusta. Efekt był taki, że dwa
    identycznie wypełnione formularze dawały różny wynik: umowa ze stawką
    płaską auto-aktywowała zamówienie, umowa ze stawką progresywną zostawiała
    je w Draft — bez żadnego komunikatu, a draftowa linia nie wchodzi ani do
    ``active_md_lines``, ani do licznika konsultantów.

    Odpowiedź daje ``effective_candidate_rate``: przy samych krokach przyszłych
    zwraca NAJBLIŻSZY nadchodzący, więc świeży kontrakt ma stawkę od razu.

    Harmonogram czytamy tylko wtedy, gdy jest wczytany. Sięgnięcie po
    niezaładowaną relację w sesji async to nie wolniejszy odczyt, tylko
    ``MissingGreenlet`` — HTTP 500 bez nagłówków CORS. Ścieżki, na których
    harmonogram ma znaczenie (PATCH zamówienia, POST przedłużenia), ładują go
    jawnie; ścieżka atomowa Flow B tworzy kontrakt bez harmonogramu, więc
    kolumna JEST tam prawdą.
    """
    if "candidate_rate_schedule" in inspect(contract).unloaded:
        return contract.rate_candidate
    return contract.effective_candidate_rate(business_today())


def _order_has_required_activation_data(order: ClientOrder) -> bool:
    """Czy draft ma komplet pól wskazanych przez formularz zamówienia.

    Numer zastępczy ``(bez numeru)`` powstaje po pierwszej edycji pojedynczego
    pola i nie jest prawdziwym numerem. „Okres” oznacza DATĘ POCZĄTKOWĄ:
    zamówienie bezterminowe (``end_date IS NULL``) jest w body-leasingu
    normalnym stanem docelowym, a nie brakiem danych — wymaganie tu obu granic
    więziło kompletne zamówienia bezterminowe w Draft na stałe (Bogusiak /
    Contract 570: numer, obie stawki i data startu wypełnione, a rekord nigdy
    nie wychodził z Draftu, bo daty końcowej z definicji nie ma).
    """

    title = (order.title or "").strip()
    base_complete = bool(
        title
        and title != "(bez numeru)"
        and order.start_date is not None
        and order.rate_client is not None
        and (
            order.rate_candidate is not None
            or (
                order.contract is not None
                and _activation_candidate_rate(order.contract) is not None
            )
        )
    )
    if not base_complete:
        return False
    effective_type = effective_standalone_order_type(order.client_id, order.order_type)
    if effective_type == OrderType.cost:
        return order.total_value is not None and order.total_value > 0
    if effective_type == OrderType.md:
        return order.md_total is not None and order.md_total > 0
    return True


def _auto_activate_unless_status_explicit(
    order: ClientOrder, *, explicit_fields: set[str]
) -> bool:
    """Heurystyka kompletności ustępuje jawnej decyzji operatora.

    ``ClientOrderUpdate.status`` jest polem publicznym, a ciąg
    ``PATCH {"status": "draft"}`` → ``DELETE`` to udokumentowana (CLAUDE.md)
    i używana realnie JEDYNA droga twardego usunięcia zamówienia z aplikacji —
    ``DELETE`` kasuje wyłącznie szkice, każdy inny status tylko anuluje. Bez
    tego warunku promocja leciała po ślepym ``setattr`` i nie odróżniała
    „draft, bo nikt jeszcze nie uzupełnił" od „draft, bo operator właśnie o to
    poprosił": kompletne zamówienie wracało z PATCH-a jako ``active``, a
    osierocone wiersze ``client_orders`` po skasowanej grupie stawały się
    nieusuwalne z interfejsu.
    """
    if "status" in explicit_fields:
        return False
    return _activate_complete_draft(order)


def _activate_complete_draft(order: ClientOrder) -> bool:
    """Promuj kompletny draft; zwróć czy nastąpiła zmiana statusu."""

    if (
        order.status != ClientOrderStatus.draft
        or not _order_has_required_activation_data(order)
    ):
        return False
    order.status = ClientOrderStatus.active
    if order.filled_at is None:
        order.filled_at = datetime.now(timezone.utc)
    return True


async def _sync_contract_after_order_extension(
    db: AsyncSession,
    order: ClientOrder,
    contract: Contract,
    *,
    actor_id: Optional[int],
) -> bool:
    """Zamówienie, które JUŻ TRWA, wskrzesza zakończony kontrakt.

    Cienki adapter na ``contract_lifecycle.sync_contract_to_live_order``.
    Cały niezmiennik — status, horyzont kontraktu i opcjonalny
    ``client_order_end_date`` — mieszka w serwisie, bo tę samą operację
    wykonują także import Nordea i linie zamówień grupowych.

    Zamówienia ``draft``/``cancelled`` są POMIJANE: szkic nie jest
    zobowiązaniem, a anulowane nie obowiązuje — żadne z nich nie jest dowodem,
    że współpraca trwa.
    """
    if order.status in (ClientOrderStatus.draft, ClientOrderStatus.cancelled):
        return False
    return await sync_contract_to_live_order(
        db,
        contract,
        order_start=order.start_date,
        order_end=order.end_date,
        actor_id=actor_id,
        today=business_today(),
    )


def _patch_requires_contract_sync(
    order: ClientOrder,
    *,
    previous_status: ClientOrderStatus,
    previous_start_date: Optional[date],
    previous_end_date: Optional[date],
) -> bool:
    """Czy PATCH jest rzeczywistym writerem cyklu życia aktywnego Orderu."""

    return order.status == ClientOrderStatus.active and (
        previous_status != ClientOrderStatus.active
        or order.start_date != previous_start_date
        or order.end_date != previous_end_date
    )


async def _materialize_group_after_activation(
    db: AsyncSession, order: ClientOrder, *, actor_id: Optional[int]
) -> None:
    """U klienta wielo-konsultantowego aktywowany szkic staje się linią grupy.

    Wspólny krok wszystkich trzech ścieżek promujących draft (create, Flow B,
    PATCH). Poza klientami z ``MULTI_CONSULTANT_ORDER_CLIENT_IDS`` (oraz dla
    zamówień kosztowych — Polkomtel) serwis jest no-opem, więc wywołanie jest
    bezwarunkowe. Efektywna stawka kosztowa idzie parametrem, bo reguła
    „harmonogram jest prawdą" mieszka tutaj (``_activation_candidate_rate``),
    a serwis nie importuje z warstwy API.
    """
    candidate_rate = order.rate_candidate
    if candidate_rate is None and order.contract is not None:
        candidate_rate = _activation_candidate_rate(order.contract)
    try:
        await materialize_group_for_activated_order(
            db, order, actor_id=actor_id, candidate_rate=candidate_rate
        )
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc


def _apply_md_order_quantity(order: ClientOrder, quantity: Optional[Decimal]) -> None:
    """„Liczba MD zamówienia” — budżet na samodzielnym szkicu MD.

    Dla jawnego, nowego typu MD pole jest wymagane przed aktywacją i przy
    materializacji przechodzi na wspólną pulę grupy. Dla rekordu legacy
    zachowuje dawną, opcjonalną semantykę budżetu linii.

    ``ck_client_orders_md_coherence`` wymaga kompletu: budżet bez stawki
    przychodowej > 0 nie przejdzie bazy, więc stawka jest tu warunkiem
    wstępnym, komunikowanym po polsku zamiast surowym IntegrityError.
    ``None`` czyści komplet pól budżetu (CHECK dopuszcza tylko wszystko albo
    nic); lustro ``md_rate_revenue`` zostaje — linia bez budżetu z samą stawką
    jest legalna od migracji 0233.
    """
    if (
        effective_standalone_order_type(order.client_id, order.order_type)
        != OrderType.md
    ):
        raise HTTPException(
            422,
            detail=(
                "Liczba MD dotyczy wyłącznie zamówienia typu MD albo "
                "historycznego klienta rozliczanego w MD."
            ),
        )
    if order.order_group_id is not None:
        # Linia w grupie ma własny tor edycji budżetu (update_line: zdarzenia
        # w historii zamówienia, przeliczenie kwoty). Tą drogą edytujemy
        # WYŁĄCZNIE samodzielne szkice.
        raise HTTPException(
            422,
            detail=(
                "To jest linia zamówienia grupowego — budżet MD edytuj "
                "w karcie zamówienia."
            ),
        )
    if quantity is None:
        order.md_total = None
        order.md_remaining = None
        order.md_input_mode = None
        order.md_input_value = None
        return
    if order.rate_client is None or order.rate_client <= 0:
        # CHECK budżetu wymaga stawki > 0 (jest dzielnikiem przy zamianie
        # kontraktora) — zero odrzucamy tu, nie IntegrityError-em przy commit.
        raise HTTPException(
            422,
            detail=(
                "Najpierw uzupełnij stawkę przychodową (większą od zera) — "
                "bez niej liczba MD nie przejdzie walidacji budżetu zamówienia."
            ),
        )
    try:
        qty = quantize_md(quantity)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    if qty <= 0:
        raise HTTPException(
            422,
            detail=(
                "Liczba MD musi być większa od zera — żeby usunąć budżet, wyczyść pole."
            ),
        )
    order.md_rate_revenue = md_rate_from_order_rate(order.rate_client)
    order.md_input_mode = INPUT_MODE_MD
    order.md_input_value = qty
    order.md_total = qty
    # Pozostałość TYMCZASOWA, ale KONIECZNA: ``ck_client_orders_md_coherence``
    # wymaga ``md_remaining`` razem z ``md_total``, a autorytatywną wartość
    # liczy dopiero ``recompute_remaining`` — która potrzebuje ``order.id``,
    # czyli flushu, czyli wiersza, który musi już przejść CHECK. Bez tej linii
    # POST zakładający zamówienie z budżetem MD wywracał się na INSERT
    # nieobsłużonym IntegrityError (500 bez CORS = „Network Error" u
    # użytkownika, zero wierszy w bazie). Dla nowego zamówienia ta wartość JEST
    # ostateczna (zero zużycia), dla istniejącego nadpisze ją przeliczenie.
    order.md_remaining = quantize_md(
        qty + Decimal(str(order.md_manual_adjustment or 0))
    )


def _refresh_md_rate_mirror(order: ClientOrder, *, explicit_fields: set[str]) -> None:
    """Lustro stawki na SAMODZIELNYM szkicu z budżetem MD.

    ``md_rate_revenue`` jest kopią ``rate_client`` (wymóg CHECK budżetu), więc
    korekta stawki przychodowej musi odświeżyć kopię — inaczej materializacja
    poniosłaby do linii stawkę sprzed korekty i rozliczenie liczyłoby się
    z innej kwoty, niż widzi operator. Wyczyszczenie stawki przy wpisanym
    budżecie dostaje czytelne 422 zamiast IntegrityError
    z ``ck_client_orders_md_coherence`` przy commicie. Linii w grupie nie
    dotykamy — jej budżet prowadzi ``update_line``.
    """
    if "rate_client" not in explicit_fields:
        return
    if order.order_group_id is not None or order.md_total is None:
        return
    if order.rate_client is None or order.rate_client <= 0:
        raise HTTPException(
            422,
            detail=(
                "Zamówienie ma wpisaną liczbę MD — wyczyść ją, zanim usuniesz "
                "lub wyzerujesz stawkę przychodową (budżet bez dodatniej "
                "stawki nie przejdzie walidacji)."
            ),
        )
    order.md_rate_revenue = md_rate_from_order_rate(order.rate_client)


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


def _normalize_monthly(
    rate: Optional[Decimal | int],
    rate_unit: Optional[RateUnit],
    billing_hours: Optional[int],
) -> Optional[Decimal | int]:
    if rate is None:
        return None
    if rate_unit == RateUnit.monthly or rate_unit is None:
        return rate
    if rate_unit == RateUnit.daily:
        return rate * 22
    if rate_unit == RateUnit.hourly:
        return rate * (billing_hours or 160)
    return rate


def _compute_monthly_margin(
    order: ClientOrder, contract: Contract, on: Optional[date] = None
) -> Optional[Decimal | int]:
    """Marża/mc dla Order: (Order.rate_client ?? stawka klienta z umowy) - stawka kandydata.

    Obie stawki umowy są rozstrzygane NA DZIEŃ ``on`` z harmonogramów
    (``effective_rate_fields``), nie czytane z kolumn ``contracts.rate_*``.
    Kolumna to cache zapisywany przy ZAPISIE umowy: krok stawki progresywnej
    albo aneks ``rate_change``, którego data już minęła, nigdy jej nie dotyka,
    więc te trzy powierzchnie (wiersz zamówienia, „ostatnie zamówienie" na
    liście kontraktorów, odpowiedź po utworzeniu zamówienia) pokazywały marżę
    z PIERWSZEGO okresu stawkowego. Wymaga wczytanych ``RATE_SCHEDULE_LOADS``.

    Stawka na poziomie ZAMÓWIENIA nadal wygrywa — to fakt o tym zamówieniu,
    a nie o umowie.

    Domyślne „dziś" to ``business_today()``, nie ``date.today()``: to drugie
    czyta zegar KONTENERA (UTC), więc krok harmonogramu z ``effective_from``
    na 1. dnia miesiąca zaczynałby obowiązywać w marży o 01:00/02:00 czasu
    warszawskiego. Ta sama kwota otwarta rano i w nocy pierwszego dnia
    miesiąca podawałaby dwie różne liczby, a objaw jest cichy — liczba jest
    poprawna, tylko opisuje inną dobę.
    """
    eff = effective_rate_fields(contract, on or business_today())
    # `is not None` zamiast `or` — stawka 0 na Orderze jest legalna i nie może
    # po cichu spadać do stawki kontraktu.
    rate_client_effective = (
        order.rate_client if order.rate_client is not None else eff["rate_client"]
    )
    rate_candidate_effective = (
        order.rate_candidate
        if order.rate_candidate is not None
        else eff["rate_candidate"]
    )
    if rate_client_effective is None or rate_candidate_effective is None:
        return None
    client_currency = (
        order.rate_client_currency or order.currency or eff["rate_client_currency"]
    ).upper()
    candidate_currency = (
        order.rate_candidate_currency or eff["rate_candidate_currency"]
    ).upper()
    if client_currency != candidate_currency:
        # This synchronous helper has no dated FX snapshot. Returning no
        # margin is safer than subtracting nominal values in different
        # currencies; PLN analytics convert both legs independently.
        return None
    monthly_client = _normalize_monthly(
        rate_client_effective,
        order.rate_unit or contract.rate_unit,
        order.billing_hours_per_month or contract.billing_hours_per_month,
    )
    monthly_cand = _normalize_monthly(
        rate_candidate_effective,
        order.rate_unit or contract.rate_unit,
        order.billing_hours_per_month or contract.billing_hours_per_month,
    )
    if monthly_client is None or monthly_cand is None:
        return None
    return monthly_client - monthly_cand


def _apply_candidate_rate(
    contract: Contract,
    rate: Optional[Decimal | int],
    *,
    actor_id: Optional[int],
    on: Optional[date] = None,
) -> None:
    """Zapisz stawkę kosztową TAM, SKĄD CZYTA ODCZYT.

    Do 21.08 ten zapis szedł wprost do kolumny ``contracts.rate_candidate``,
    a wszystkie odczyty pieniędzy (marża wiersza zamówienia, karta
    kontraktora, ``/my-clients``, panel admina, analityka) idą przez
    ``effective_rate_fields`` → ``_resolve_scheduled_rate``, który schodzi do
    kolumny WYŁĄCZNIE wtedy, gdy harmonogram jest pusty. Dla kontraktu ze
    stawką progresywną albo z aneksem ``rate_change`` — czyli dokładnie dla
    populacji, dla której harmonogram powstał — zapis był więc ignorowany
    przez cały system. Użytkownik dostawał 200, pole na ekranie pokazywało
    nową wartość (bo czytało tę samą kolumnę), a pieniądze się nie zmieniały:
    awaria cicha w najgorszą stronę, bez błędu i bez logu.

    Reguła: harmonogram jest prawdą, więc zmiana stawki dopisuje do niego
    KROK obowiązujący od dziś. To ten sam zapis, co aneks ``rate_change`` —
    historia zostaje nietknięta, zmienia się przyszłość. Ponowna edycja tego
    samego dnia nadpisuje krok zamiast dokładać kolejny (rozstrzygnięcie i
    tak byłoby to samo — ``_resolve_scheduled_rate`` przy remisie dat wybiera
    ostatnio wstawiony — ale historia nie musi puchnąć od poprawek literówek).

    Kolumna jest nadal zapisywana: pozostaje cache'em dla umów BEZ
    harmonogramu, karmi ``calculate_margin()`` (a po niej filtr „marża od"
    w rejestrze umów, który filtruje po utrwalonej kolumnie ``contracts.margin``,
    nie po wyrażeniu) i jest tym samym, co zapisuje ``contracts.update_contract``
    po podmianie harmonogramu.

    Wymaga wczytanego ``contract.candidate_rate_schedule``.
    """
    today = on or business_today()
    schedule = contract.candidate_rate_schedule or []
    if schedule and rate is None:
        # Wyczyszczenie stawki prowadzonej harmonogramem jest niewykonalne:
        # krok nie może mieć pustej stawki (``rate`` NOT NULL), a samo
        # wyzerowanie kolumny nic by nie zmieniło, bo resolver i tak czyta
        # harmonogram. Odmowa zamiast cichego no-opu.
        raise HTTPException(
            409,
            detail=(
                "Stawka kosztowa jest prowadzona harmonogramem — "
                "wyczyść ją w umowie, edytując harmonogram stawek."
            ),
        )
    contract.rate_candidate = rate
    if schedule:
        same_day = [step for step in schedule if step.effective_from == today]
        if same_day:
            same_day[-1].rate = rate
        else:
            schedule.append(
                ContractCandidateRate(
                    rate=rate,
                    effective_from=today,
                    note="Zmiana stawki z formularza zamówienia",
                    created_by=actor_id,
                )
            )
    # Filtr „marża od" w rejestrze umów porównuje UTRWALONĄ kolumnę
    # `contracts.margin`, a nie wyrażenie — bez tego przeliczenia kontrakt po
    # zmianie stawki kosztowej kwalifikowałby się po nieistniejącej już
    # wartości: zostawałby w wynikach filtra, do którego już nie należy, albo
    # z niego wypadał, mimo że należy. `PATCH /api/contracts/{id}` robi
    # dokładnie ten sam krok na końcu.
    contract.margin = contract.calculate_margin()


# F-13 / P0.12: globalnie kwoty widzą role z VIEW_FINANCE. Przypisany Delivery
# Lead ma wąski wyjątek dla zamówień swojego klienta. TCM zachowuje bezpieczny
# widok operacyjny bez kwot i bez metadanych rate-bearing plików PO.
_ORDER_FINANCE_FIELDS = (
    "rate_candidate",
    "rate_client",
    "total_value",
    "monthly_margin",
    "currency",
    "rate_client_currency",
    "rate_candidate_currency",
)
# Klucze pól finansowych w fields_confidence odczytu PDF — redagowane dla ról
# bez VIEW_FINANCE (obecność klucza sama zdradza, że PO zawiera stawkę/wartość).
_EXTRACTION_FINANCE_CONF_KEYS = frozenset(
    {
        "rate_client",
        "rate_client_md",
        "rate_client_gross",
        "total_value",
        "currency",
        "rate_unit",
    }
)
_CONTRACTOR_FINANCE_FIELDS = (
    "rate_candidate",
    "rate_client_currency",
    "rate_candidate_currency",
    "latest_order_rate_client",
    "latest_order_monthly_margin",
)
_ORDER_FINANCE_WRITE_FIELDS = frozenset(
    {
        "rate_client",
        "rate_candidate",
        "total_value",
        "currency",
        "rate_client_currency",
        "rate_candidate_currency",
        "rate_unit",
        "billing_hours_per_month",
    }
)
# Podzbiór, który wolno zapisać PRZYPISANEMU Delivery Leadowi. Admin ma pełen
# zestaw. Wszystkie pola poniżej opisują wyłącznie snapshot jednego zamówienia;
# zmiana jednostki przelicza jego dwie stawki, ale nie dotyka Contract ani
# sąsiednich zamówień. Pozostałe admin-only pola nie są tu dopuszczane.
_DL_ORDER_FINANCE_WRITE_FIELDS = frozenset(
    {
        "rate_client",
        "rate_candidate",
        "total_value",
        "currency",
        "rate_client_currency",
        "rate_candidate_currency",
        # These fields now describe one order snapshot; they no longer rewrite
        # Contract or the history of sibling orders.
        "rate_unit",
        "billing_hours_per_month",
    }
)


async def _dl_assigned_to_client(db: AsyncSession, user, client_id: int) -> bool:
    """Czy ten user ma JAWNE przypisanie Delivery Leada do tego klienta.

    Dostęp operacyjny do klienta jest globalny dla roli DL, ale ten helper
    celowo zachowuje węższy wyjątek finansowy własnego portfela.
    """

    from app.models.team_structure import DeliveryLeadClientAssignment

    row = await db.scalar(
        select(DeliveryLeadClientAssignment.id).where(
            DeliveryLeadClientAssignment.client_id == client_id,
            DeliveryLeadClientAssignment.delivery_lead_user_id == user.id,
        )
    )
    return row is not None


def _can_manage_order_finance(user, *, dl_assigned: bool) -> bool:
    """Kto zapisuje kwoty na zamówieniach TEGO klienta.

    Admin zawsze; Delivery Lead WYŁĄCZNIE na kliencie, do którego jest jawnie
    przypisany. To rozszerzenie pierwotnej reguły „tylko admin" (F-13/P0.12):
    DL prowadzi zamówienia klienta na co dzień i to on uzupełnia draft, więc
    odsyłanie każdej stawki do admina zamieniało rejestr w prośbę o czynność,
    której adresat nie mógł wykonać.

    Predykat CELOWO sprawdza rolę i przypisanie niezależnie. TAC, HoR, TCM,
    recruiter i sourcer: zawsze False.

    Odczyt ma osobny predykat ``_order_finance_visible``: Finance widzi kwoty
    przez ``VIEW_FINANCE``, ale nie przechodzi przez ten guard zapisu.
    """

    if user.has_role(UserRole.admin):
        return True
    return user.has_role(UserRole.delivery_lead) and dl_assigned


def _order_finance_visible(user, *, can_finance: bool) -> bool:
    """Czy pokazywać kwoty: klasyczne VIEW_FINANCE albo przypisany DL."""

    return can_finance or user_has_capability(user, AnalyticsCapability.VIEW_FINANCE)


def _assert_order_finance_write_allowed(
    user, supplied_fields, *, can_finance: bool = False
) -> None:
    """Reject amount writes from operational-only roles before touching the DB.

    ``can_finance`` DOMYŚLNIE False i jest tylko ROZSZERZENIEM: admin przechodzi
    niezależnie od niego. Dzięki temu endpoint, który zapomni policzyć flagę,
    zamyka się dla wszystkich poza adminem, zamiast otwierać dla wszystkich —
    bramka nie zależy od tego, czy wywołujący pamiętał o argumencie.

    Przypisany Delivery Lead dostaje wyłącznie jawnie allowlistowane pola
    finansowe zamówienia. Jednostka i godziny są snapshotem jednego zamówienia,
    więc mogą być zmieniane razem ze stawkami bez przepisywania Contract ani
    zamówień historycznych.
    """

    is_admin = user.has_role(UserRole.admin)
    allowed = (
        _ORDER_FINANCE_WRITE_FIELDS
        if is_admin
        else (_DL_ORDER_FINANCE_WRITE_FIELDS if can_finance else frozenset())
    )
    forbidden = sorted(
        set(supplied_fields).intersection(_ORDER_FINANCE_WRITE_FIELDS) - allowed
    )
    # Orders are candidate-bearing. Finance works through person-free finance
    # APIs; only Admin and the client's assigned Delivery Lead may mutate
    # amounts on this mixed operational resource.
    if forbidden:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "finance_fields_forbidden",
                "fields": forbidden,
            },
        )


async def _assert_no_pending_group_line_offboarding(
    db: AsyncSession, order: ClientOrder
) -> None:
    """Keep legacy standalone routes from bypassing the MD decision workflow."""

    if order.order_group_id is None:
        return
    pending_case_id = await db.scalar(
        select(ClientOrderOffboardingCase.id)
        .where(
            ClientOrderOffboardingCase.order_id == order.id,
            ClientOrderOffboardingCase.status == OFFBOARDING_STATUS_PENDING,
        )
        .limit(1)
    )
    if pending_case_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "offboarding_decision_required",
                "message": (
                    "Najpierw podejmij decyzję o pozostałej puli MD po "
                    "zakończeniu współpracy konsultanta."
                ),
            },
        )


def _flow_b_finance_kwargs(
    payload: NewContractorOrderRequest,
    user,
    *,
    can_finance: bool = False,
) -> tuple[dict[str, object], dict[str, object]]:
    """Build finance kwargs only for finance-capable callers; others get empty dicts."""

    _assert_order_finance_write_allowed(
        user, payload.model_fields_set, can_finance=can_finance
    )
    if not user.has_role(UserRole.admin) and not (
        payload.model_fields_set & _ORDER_FINANCE_WRITE_FIELDS
    ):
        # Rekord czysto OPERACYJNY: nie podano żadnej kwoty, więc nie ma czego
        # walidować. Bez tego warunku przypisany Delivery Lead zakładający
        # kontraktora bez stawek dostawał 422 „wymagane rate_client i
        # rate_candidate" — reguła kompletności par stawek miała pilnować, żeby
        # nie dało się ustawić POŁOWY cennika, a nie wymuszać cennik na kimś,
        # kto o żadnym nie wspomniał.
        return {}, {}

    missing = [
        field
        for field in ("rate_client", "rate_candidate")
        if getattr(payload, field) is None
    ]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "code": "admin_finance_fields_required",
                "fields": missing,
            },
        )

    # `rate_unit` NIE jest tu ustawiane: jednostka nie jest kwotą i musi być
    # nadana KAŻDEMU rekordowi (także czysto operacyjnemu bez stawek), więc
    # rozstrzyga ją endpoint — z `payload.rate_unit` albo z domyślnej jednostki
    # klienta. Gdyby wracała w tych kwargach, rekord operacyjny (pusty słownik)
    # znów dostawałby serwerowy default `monthly`.
    supplied = payload.model_fields_set
    legacy = _normalize_contract_currency(payload.currency or "PLN", "currency")
    client_currency = (
        _normalize_contract_currency(
            payload.rate_client_currency, "rate_client_currency"
        )
        if "rate_client_currency" in supplied
        else legacy
    )
    candidate_currency = (
        _normalize_contract_currency(
            payload.rate_candidate_currency, "rate_candidate_currency"
        )
        if "rate_candidate_currency" in supplied
        else legacy
    )
    if (
        "currency" in supplied
        and "rate_client_currency" in supplied
        and client_currency != legacy
    ):
        _raise_currency_conflict(["rate_client_currency"])
    billing_hours = payload.billing_hours_per_month or 160
    contract_kwargs: dict[str, object] = {
        "rate_client": payload.rate_client,
        "rate_candidate": payload.rate_candidate,
        "currency": client_currency,
        "rate_client_currency": client_currency,
        "rate_candidate_currency": candidate_currency,
        "billing_hours_per_month": billing_hours,
    }
    order_kwargs: dict[str, object] = {
        "rate_candidate": payload.rate_candidate,
        "rate_client": payload.rate_client,
        "billing_hours_per_month": billing_hours,
        "total_value": payload.total_value,
        # Zamówienie reprezentuje przychód od klienta.
        "currency": client_currency,
        "rate_client_currency": client_currency,
        "rate_candidate_currency": candidate_currency,
    }
    return contract_kwargs, order_kwargs


def _redact_order_finance(order: ClientOrderRead) -> ClientOrderRead:
    for field in _ORDER_FINANCE_FIELDS:
        setattr(order, field, None)
    return order


def _is_read_only_tcm(user: User) -> bool:
    """TCM ceiling for Delivery orders, irrespective of HoR/TAC secondary roles.

    HoR and TAC do not independently enter Delivery, so only Admin, assigned
    Delivery Lead, or Finance can supersede the TCM read-only projection here.
    """

    return user.has_role(UserRole.talent_community_manager) and not user.has_any_role(
        UserRole.admin,
        UserRole.delivery_lead,
        UserRole.finance,
    )


def _redact_order_document_metadata(order: ClientOrderRead) -> ClientOrderRead:
    """Hide affordances for PO files that the TCM role cannot download."""

    order.filename = None
    order.has_file = False
    order.content_type = None
    order.size_bytes = None
    return order


def _redact_contractor_finance(item: ContractWithOrdersRead) -> ContractWithOrdersRead:
    for field in _CONTRACTOR_FINANCE_FIELDS:
        setattr(item, field, None)
    for order in item.orders:
        _redact_order_finance(order)
    return item


def _order_response_for_user(
    order: ClientOrderRead,
    user,
    *,
    can_finance: bool = False,
) -> ClientOrderRead:
    if not _order_finance_visible(user, can_finance=can_finance):
        _redact_order_finance(order)
    if _is_read_only_tcm(user):
        _redact_order_document_metadata(order)
    return order


def _build_order_read(
    order: ClientOrder,
    contract: Optional[Contract],
    candidate: Optional[Candidate],
    job_title: Optional[str],
) -> ClientOrderRead:
    """Złożenie ``ClientOrderRead`` z obiektów, które wołający ma już w ręku.

    Czysta funkcja, ZERO zapytań — po to, żeby lista zamówień mogła ją wołać
    w pętli. Skąd wołający weźmie kontrakt/kandydata/tytuł rekrutacji, jest
    jego sprawą: widok listy bierze je z relacji zaciągniętych jednym
    `selectinload`, pojedyncze endpointy dopytują (``_order_to_read``).
    """
    monthly_margin = _compute_monthly_margin(order, contract) if contract else None

    return ClientOrderRead(
        id=order.id,
        client_id=order.client_id,
        contract_id=order.contract_id,
        job_id=order.job_id,
        framework_contract_id=order.framework_contract_id,
        title=order.title,
        description=order.description,
        status=order.status,
        # Preserve the raw compatibility marker on the wire.  Legacy rows use
        # NULL to distinguish them from explicitly typed drafts in the UI;
        # effective type resolution belongs in policy checks and export only.
        order_type=order.order_type,
        start_date=order.start_date,
        end_date=order.end_date,
        rate_candidate=order.rate_candidate,
        rate_client=order.rate_client,
        rate_unit=order.rate_unit,
        billing_hours_per_month=order.billing_hours_per_month,
        total_value=order.total_value,
        currency=order.currency,
        rate_client_currency=order.rate_client_currency or order.currency,
        rate_candidate_currency=order.rate_candidate_currency,
        project_part=order.project_part,
        filename=order.filename,
        has_file=order.file_path is not None,
        content_type=order.content_type,
        size_bytes=order.size_bytes,
        created_by_user_id=order.created_by_user_id,
        notes=order.notes,
        created_at=order.created_at,
        updated_at=order.updated_at,
        candidate_id=contract.candidate_id if contract else None,
        candidate_name=candidate.name if candidate else None,
        contract_status=contract.status.value if contract and contract.status else None,
        job_title=job_title,
        monthly_margin=monthly_margin,
        days_to_end=_days_to(order.end_date),
        md_quantity=(
            order.md_input_value
            if order.md_input_mode == INPUT_MODE_MD
            else order.md_total
        ),
    )


async def _order_to_read(db: AsyncSession, order: ClientOrder) -> ClientOrderRead:
    """Pełny widok Orderu dla endpointów operujących na JEDNYM zamówieniu.

    Dopytuje kandydata i rekrutację, bo na tych ścieżkach `order` przychodzi
    z `selectinload(ClientOrder.contract)` i niczym więcej — a lazy-load na
    sesji async to `MissingGreenlet`, czyli 500 bez CORS. Widok listy tego
    NIE używa: tam te same dwa zapytania mnożyły się przez liczbę zamówień
    (klient z 30 kontraktorami po 5 zamówień = ~300 zbędnych round-tripów),
    mimo że dane leżały już w pamięci.

    Umowa jest pobierana Z HARMONOGRAMAMI stawek nawet wtedy, gdy
    `order.contract` jest już w pamięci: marża wiersza liczy się z kroku
    obowiązującego dziś, a wołający wpinają tu `selectinload(ClientOrder.contract)`
    BEZ zagnieżdżonych harmonogramów. Zapytanie trafia w identity map sesji,
    więc kosztuje jeden dociąg relacji, nie drugi obiekt.
    """
    contract = (
        await db.scalar(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .where(Contract.id == order.contract_id)
        )
        if order.contract_id is not None
        else None
    )
    candidate: Optional[Candidate] = None
    if contract:
        candidate = await db.scalar(
            select(Candidate).where(Candidate.id == contract.candidate_id)
        )
    job_title = None
    if order.job_id:
        job = await db.scalar(select(Job).where(Job.id == order.job_id))
        job_title = job.title if job else None

    return _build_order_read(order, contract, candidate, job_title)


# ── Grouped list (main GET) ────────────────────────────────────────────────


@router.get(
    "/{client_id}/orders/default-rate-unit",
    response_model=ClientOrderDefaultRateUnit,
)
async def get_client_default_rate_unit(
    client_id: int,
    user: OrderSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Jednostka stawki proponowana domyślnie w formularzach zamówień klienta.

    Wyliczona z istniejących zamówień klienta (najczęstsza NIE-miesięczna).
    Front używa jej jako wartości początkowej pola „jednostka stawki" w „Nowym
    kontraktorze" i przy uzupełnianiu — zamiast twardego `monthly`. Sama
    jednostka nie jest kwotą, więc odczyt ma tę samą bramkę co lista zamówień
    (bez redakcji finansowej). Zdefiniowana PRZED ``/{client_id}/orders/{order_id}``,
    bo tamten konwertuje `order_id` do `int` — literalna ścieżka i tak nie
    trafiłaby w regex `\\d+`, ale kolejność czyni to jawnym.
    """
    await _require_safe_client_order_read(db, user, client_id)
    return ClientOrderDefaultRateUnit(
        rate_unit=await default_rate_unit_for_client(db, client_id)
    )


@router.get("/{client_id}/orders", response_model=ClientOrdersGroupedResponse)
async def list_contractors_with_orders(
    client_id: int,
    user: OrderSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca listę kontraktorów (per Contract) z historią Orderów per Contract.

    UI: tab "Zamówienia & Kontrakty" pokazuje listę kart (1 karta = 1 kontraktor).
    """
    await _require_safe_client_order_read(db, user, client_id)

    contracts = list(
        (
            await db.execute(
                select(Contract)
                .options(
                    *RATE_SCHEDULE_LOADS,
                    selectinload(Contract.candidate),
                    # Rekrutacja POJEDYNCZEGO zamówienia — `ClientOrder.job_id`
                    # bywa inne niż `Contract.job_id` (przedłużenie potrafi
                    # przyjść z innego zlecenia), więc `Contract.job` niżej go
                    # nie zastąpi. `selectin` dociąga wszystkie te rekrutacje
                    # JEDNYM `IN`-em na całą odpowiedź, zamiast jednego
                    # zapytania na zamówienie.
                    selectinload(Contract.client_orders).selectinload(ClientOrder.job),
                    selectinload(Contract.job),
                )
                .where(Contract.client_id == client_id)
                .order_by(Contract.start_date.desc().nullslast())
            )
        ).scalars()
    )

    items: list[ContractWithOrdersRead] = []
    today = business_today()
    for c in contracts:
        orders_list = sorted(
            # Linie kosztowe/MD mają własny rejestr grup. Wspólny widok typów
            # osadza ten endpoint jako sekcję „Okresowe”, więc pokazanie ich
            # również tutaj dublowałoby każde historyczne zamówienie. Samych
            # rekordów nie zmieniamy — filtr dotyczy wyłącznie prezentacji.
            [
                order
                for order in (c.client_orders or [])
                if order.order_group_id is None
            ],
            key=lambda o: o.start_date or date.min,
            reverse=True,
        )
        latest = orders_list[0] if orders_list else None

        # JEDNO źródło stawek na tę odpowiedź. Do 21.08 marża szła z
        # harmonogramów, a `rate_candidate` i fallback stawki przychodowej —
        # z cache'owanych kolumn `contracts.rate_*`. Karta kontraktora
        # renderuje obie liczby obok siebie, więc kontrakt z krokiem
        # progresywnym, który już wszedł w życie, pokazywał
        # „stawka przychodowa − stawka kosztowa ≠ marża" i wzrokiem nie dało
        # się rozstrzygnąć, która liczba jest prawdziwa. Kolumny zapisuje
        # wyłącznie ZAPIS kontraktu — żadne zadanie w tle nie odświeża ich
        # w dniu wejścia kroku w życie. Schematy są już wczytane
        # (`RATE_SCHEDULE_LOADS` w `.options(...)` wyżej), więc to zero
        # dodatkowych zapytań.
        eff = effective_rate_fields(c, today)

        latest_margin = _compute_monthly_margin(latest, c, today) if latest else None
        latest_end = latest.end_date if latest else None
        days_to_end = (latest_end - today).days if latest_end else None

        # Bez dopytywania bazy: kandydat i rekrutacja są już w pamięci z
        # `selectinload` wyżej. Wcześniej szło tu `_order_to_read`, czyli
        # dwa SELECT-y na KAŻDE zamówienie każdego kontraktora.
        orders_read = [
            _build_order_read(o, c, c.candidate, o.job.title if o.job else None)
            for o in orders_list
        ]

        items.append(
            ContractWithOrdersRead(
                contract_id=c.id,
                candidate_id=c.candidate_id,
                candidate_name=(
                    f"{c.candidate.name} {c.candidate.lastname}".strip()
                    if c.candidate
                    else ""
                ),
                contract_status=c.status.value,
                contract_start_date=c.start_date,
                contract_end_date=c.end_date,
                rate_candidate=eff["rate_candidate"],
                rate_client_currency=eff["rate_client_currency"],
                rate_candidate_currency=eff["rate_candidate_currency"],
                rate_unit=c.rate_unit.value,
                billing_hours_per_month=c.billing_hours_per_month or 160,
                initial_job_id=c.job_id,
                initial_job_title=c.job.title if c.job else None,
                latest_order_id=latest.id if latest else None,
                latest_order_end_date=latest_end,
                latest_order_rate_client=(
                    # `is not None` — stawka 0 na Orderze nie spada do kontraktu.
                    (
                        latest.rate_client
                        if latest.rate_client is not None
                        else eff["rate_client"]
                    )
                    if latest
                    else eff["rate_client"]
                ),
                latest_order_monthly_margin=latest_margin,
                days_to_latest_end=days_to_end,
                orders=orders_read,
            )
        )

    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    if not _order_finance_visible(user, can_finance=can_finance):
        for item in items:
            _redact_contractor_finance(item)
    if _is_read_only_tcm(user):
        for item in items:
            for order in item.orders:
                _redact_order_document_metadata(order)

    return ClientOrdersGroupedResponse(
        contractors=items,
        total_contractors=len(items),
        # Front nie zna przypisań DL, więc bez tej flagi musiałby zgadywać,
        # czy pokazać pola stawek — i pokazywałby kontrolkę, która kończy się
        # 403 na zapisie. Cała zakładka dotyczy jednego klienta, więc jedna
        # flaga na odpowiedź wystarcza.
        can_manage_finance=can_finance,
    )


@router.post("/{client_id}/orders/export")
async def export_client_orders(
    client_id: int,
    payload: ClientOrderExportRequest,
    user: UnifiedOrderExportReader,
    db: AsyncSession = Depends(get_db),
):
    """Export exactly the ordered rows visible in the unified client view.

    ``order_ids`` remains the backwards-compatible standalone-order request.
    ``items`` is the unified contract: it preserves the mixed group/order
    sequence supplied by the UI and adds the group budget plus order-type
    columns to one workbook.
    """

    client = await _assert_client(db, client_id)
    unified = payload.items is not None
    requested = (
        [(item.kind, item.id) for item in payload.items]
        if payload.items is not None
        else [("order", order_id) for order_id in dict.fromkeys(payload.order_ids)]
    )
    requested_order_ids = [item_id for kind, item_id in requested if kind == "order"]
    requested_group_ids = [item_id for kind, item_id in requested if kind == "group"]

    if unified and not requested:
        # Pusty arkusz nadal jest odczytem zasobu klienta. Nie pozwalamy, by
        # `{items: []}` omijało przypisanie DL tylko dlatego, że nie ma ID,
        # po którym późniejsze gałęzie wykonałyby właściwy guard.
        from app.api.client_order_groups import _require_group_read

        await _require_group_read(db, user, client_id)

    orders_by_id: dict[int, tuple[ContractWithOrdersRead, ClientOrderRead]] = {}
    if not unified or requested_order_ids:
        # Standalone order rows use the same business-read audience as the
        # unified order list. Finance is organization-wide; Delivery Lead still
        # passes the normal client-assignment resolver inside the list handler.
        if not user.has_any_role(
            UserRole.admin,
            UserRole.head_of_recruitment,
            UserRole.delivery_lead,
            UserRole.finance,
            UserRole.tac,
        ):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                detail="Brak dostępu do zamówień okresowych tego klienta",
            )
        grouped = await list_contractors_with_orders(client_id, user, db)
        for contractor in grouped.contractors:
            for order in contractor.orders:
                orders_by_id[order.id] = (contractor, order)
        if any(order_id not in orders_by_id for order_id in requested_order_ids):
            # Do not reveal whether an ID belongs to another client.
            raise HTTPException(404, detail="Nie znaleziono zamówienia u tego klienta")

    group_models_by_id: dict[int, ClientOrderGroup] = {}
    group_reads_by_id: dict[int, tuple[object, str]] = {}
    if requested_group_ids:
        # Imported lazily to keep the two routers independently importable.
        from app.api.client_order_groups import (
            _can_see_finance,
            _group_to_read,
            _require_group_read,
        )
        from app.services.order_types import effective_group_order_type
        from app.services.shared_md_orders import (
            shared_md_used_totals,
            uses_shared_md_pool,
        )

        await _require_group_read(db, user, client_id)
        group_models = list(
            (
                await db.execute(
                    select(ClientOrderGroup).where(
                        ClientOrderGroup.client_id == client_id,
                        ClientOrderGroup.id.in_(requested_group_ids),
                    )
                )
            ).scalars()
        )
        group_models_by_id = {group.id: group for group in group_models}
        if any(group_id not in group_models_by_id for group_id in requested_group_ids):
            raise HTTPException(404, detail="Nie znaleziono zamówienia u tego klienta")

        shared_md_used_by_group = await shared_md_used_totals(
            db, (group.id for group in group_models if uses_shared_md_pool(group))
        )
        for group_id in requested_group_ids:
            group_model = group_models_by_id[group_id]
            group = await _group_to_read(
                db,
                group_model,
                with_finance=await _can_see_finance(db, user, client_id),
                precomputed_md_budget_used=(
                    shared_md_used_by_group[group_id]
                    if uses_shared_md_pool(group_model)
                    else None
                ),
            )
            type_label = order_type_export_label(
                effective_group_order_type(group_model)
            )
            group_reads_by_id[group_id] = (group, type_label)

    # Arkusz opisuje stan NA DZIŚ: jeden wiersz na konsultanta, z zamówieniem,
    # które właśnie obowiązuje. Historia i zamówienia jeszcze nierozpoczęte
    # wchodziły do pliku razem z bieżącym, więc ta sama osoba pojawiała się
    # w nim tyle razy, ile zamówień przewinęło się przez jej kontrakt.
    # Deduplikacja idzie po KONTRAKCIE, nie po imieniu: imiona się powtarzają,
    # a ta sama osoba u tego samego klienta ma dokładnie jeden kontrakt.
    today = business_today()
    exported_contract_ids: set[int] = set()

    # Status i okres muszą zgodzić się OBA. Linia domknięta bez daty („zakończ"
    # bez wpisanej daty końca) przechodzi test okresu, a zamówienie z datą
    # w przyszłości bywa jeszcze szkicem — każde z tych kryteriów osobno
    # wpuszcza do arkusza kogoś, kto dziś u klienta nie pracuje.
    closed_statuses = {
        ClientOrderStatus.completed.value,
        ClientOrderStatus.cancelled.value,
    }

    def _status_value(raw: object) -> str:
        # `ClientOrderStatus(str, Enum)` — `str(...)` daje „ClientOrderStatus.
        # completed", nie „completed", więc porównanie po `str()` NIGDY by nie
        # trafiło i filtr statusu byłby martwy. Linie grup niosą już czysty str.
        return str(getattr(raw, "value", raw))

    def _group_line_filter(group: object):
        """Filtr obsady JEDNEJ grupy — okres linii, a w jego braku okres grupy.

        Linie zwykle nie niosą własnych dat i dziedziczą okres zamówienia (tak
        też renderuje je arkusz). Filtr czytający wyłącznie kolumny linii
        przepuszczałby więc CAŁĄ obsadę zamówienia zakończonego rok temu.
        """

        group_start = getattr(group, "start_date", None)
        group_end = getattr(group, "end_date", None)

        def _take(line: object) -> bool:
            if _status_value(getattr(line, "status", "")) in closed_statuses:
                return False
            start = getattr(line, "start_date", None) or group_start
            end = getattr(line, "end_date", None) or group_end
            if not is_current_order_period(start, end, today):
                return False
            contract_id = getattr(line, "contract_id", None)
            if contract_id is None:
                return True
            if contract_id in exported_contract_ids:
                return False
            exported_contract_ids.add(contract_id)
            return True

        return _take

    rows: list[OrderExportRow] = []
    for kind, item_id in requested:
        if kind == "group":
            group, type_label = group_reads_by_id[item_id]
            rows.extend(
                replace(row, order_type=type_label)
                for row in export_rows_for_group(
                    group,  # type: ignore[arg-type]
                    include_line=_group_line_filter(group),
                )
            )
            continue
        contractor, order = orders_by_id[item_id]
        if _status_value(order.status) in closed_statuses:
            continue
        if not is_current_order_period(order.start_date, order.end_date, today):
            continue
        if contractor.contract_id in exported_contract_ids:
            continue
        exported_contract_ids.add(contractor.contract_id)
        rows.append(
            OrderExportRow(
                consultant_name=contractor.candidate_name,
                order_number=order.title,
                cost_rate=(
                    order.rate_candidate
                    if order.rate_candidate is not None
                    else contractor.rate_candidate
                ),
                revenue_rate=order.rate_client,
                start_date=order.start_date,
                end_date=order.end_date,
                order_type=order_type_export_label(
                    effective_standalone_order_type(client_id, order.order_type)
                ),
            )
        )

    content = await run_in_threadpool(
        build_orders_workbook,
        rows,
        include_model_columns=unified,
        include_order_type=unified,
    )
    filename = orders_export_filename(client_display_name(client))
    return Response(
        content=content,
        media_type=(
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── Autocomplete for "Dodaj przedłużenie" ──────────────────────────────────


@router.get(
    "/{client_id}/contracts-with-orders",
    response_model=list[ContractWithOrdersRead],
)
async def list_active_contracts_for_extension(
    client_id: int,
    user: OrderSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista aktywnych Contractów + ich latest Order — dla autocomplete w
    "Dodaj przedłużenie".
    """
    # Reuse main list (which already redacts finance fields for non-VIEW_FINANCE).
    resp = await list_contractors_with_orders(client_id, user, db)
    return [
        c
        for c in resp.contractors
        if c.contract_status in ("active", "ending", "draft")
    ]


# ── Single Order CRUD ──────────────────────────────────────────────────────


@router.get("/{client_id}/orders/{order_id}", response_model=ClientOrderRead)
async def get_order(
    client_id: int,
    order_id: int,
    user: OrderSafeReadUser,
    db: AsyncSession = Depends(get_db),
):
    await _require_safe_client_order_read(db, user, client_id)
    order = await db.scalar(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract))
        .where(
            ClientOrder.id == order_id,
            ClientOrder.client_id == client_id,
        )
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")
    result = await _order_to_read(db, order)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    if not _order_finance_visible(user, can_finance=can_finance):
        _redact_order_finance(result)
    if _is_read_only_tcm(user):
        _redact_order_document_metadata(result)
    return result


@router.post(
    "/{client_id}/orders",
    response_model=ClientOrderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_extension(
    client_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    contract_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    order_type: OrderType = Form(OrderType.periodic),
    order_status: ClientOrderStatus = Form(ClientOrderStatus.active),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    rate_candidate: Optional[Decimal] = Form(None),
    rate_client: Optional[Decimal] = Form(None),
    rate_unit: Optional[RateUnit] = Form(None),
    billing_hours_per_month: Optional[int] = Form(None, ge=1),
    total_value: Optional[str] = Form(None),
    currency: Optional[str] = Form(None),
    rate_client_currency: Optional[str] = Form(None),
    rate_candidate_currency: Optional[str] = Form(None),
    framework_contract_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    project_part: Optional[str] = Form(None),
    md_quantity: Optional[Decimal] = Form(None),
):
    """Flow A — "Dodaj przedłużenie": tworzy Order pod istniejącym Contract."""
    from decimal import InvalidOperation

    supplied_finance_fields = {
        field
        for field, value in {
            "rate_candidate": rate_candidate,
            "rate_client": rate_client,
            "rate_unit": rate_unit,
            "billing_hours_per_month": billing_hours_per_month,
            "total_value": total_value,
            "currency": currency,
            "rate_client_currency": rate_client_currency,
            "rate_candidate_currency": rate_candidate_currency,
        }.items()
        if value is not None
    }
    await _assert_client(db, client_id)
    if file is not None:
        await _require_order_file_read(db, user, client_id)
    _assert_allowed_order_type(client_id, order_type)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    _assert_order_finance_write_allowed(
        user, supplied_finance_fields, can_finance=can_finance
    )

    # „Część umowy" — wymagana dla Centrum e-Zdrowia (także przy przedłużeniu),
    # zabroniona u pozostałych klientów (ticket #3, bramka po client_id).
    try:
        project_part = validate_project_part(client_id, project_part, require=True)
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None

    contract = await db.scalar(
        select(Contract)
        # Harmonogram stawki kandydata dociągany JAWNIE: bramka
        # `_activation_candidate_rate` niżej pyta o stawkę OBOWIĄZUJĄCĄ, a nie
        # o cache'owaną kolumnę. Bez tego `selectinload` sięgnięcie po
        # harmonogram byłoby w sesji async `MissingGreenlet` (HTTP 500 bez
        # CORS), a z ostrożnościowym fallbackiem — cichym powrotem do kolumny,
        # czyli dokładnie do defektu, który ta bramka zamyka.
        .options(*RATE_SCHEDULE_LOADS)
        .where(Contract.id == contract_id, Contract.client_id == client_id)
    )
    if contract is None:
        raise HTTPException(
            400, detail="contract_id must reference a Contract of this client"
        )
    # Zamówienie okresowe obok żywej linii MD to drugi, równoległy zapis tej
    # samej współpracy — a oba wiszą na TYM SAMYM kontrakcie, więc zakończenie
    # jednego domykało drugie. Bramka stoi tylko przy typie okresowym: szkic
    # kosztowy/MD z tego formularza materializuje się w linię grupy, więc
    # niczego nie dubluje.
    if order_type == OrderType.periodic:
        await assert_no_open_md_group_line(db, contract.id)

    effective = effective_rate_fields(contract, start_date or business_today())
    # Przedłużenie DZIEDZICZY jednostkę kontraktu (razem z jego stawkami), więc
    # NIE wymuszamy tu domyślnej jednostki klienta: kwoty bez jawnej wartości są
    # przeliczane z `contract.rate_unit` na `resolved_unit`, a podmiana jednostki
    # na inną niż kontrakt zniekształciłaby dziedziczoną kwotę (×h/×dni). Domyślną
    # jednostkę klienta stosuje wyłącznie tworzenie NOWEGO zamówienia
    # (`contract-with-order`), gdzie stawek nie ma skąd dziedziczyć.
    resolved_unit = rate_unit or contract.rate_unit
    resolved_billing_hours = (
        billing_hours_per_month or contract.billing_hours_per_month or 160
    )
    # Values supplied by the form are already expressed in resolved_unit. A
    # missing value is inherited from Contract and therefore must be converted
    # when the operator selected a different unit for this order.
    resolved_candidate_rate = (
        rate_candidate
        if rate_candidate is not None
        else convert_order_rate(
            effective["rate_candidate"],
            contract.rate_unit,
            resolved_unit,
            resolved_billing_hours,
        )
    )
    resolved_client_rate = (
        rate_client
        if rate_client is not None
        else convert_order_rate(
            effective["rate_client"],
            contract.rate_unit,
            resolved_unit,
            resolved_billing_hours,
        )
    )
    legacy_currency = _normalize_contract_currency(
        currency or effective["rate_client_currency"], "currency"
    )
    resolved_client_currency = _normalize_contract_currency(
        rate_client_currency or legacy_currency, "rate_client_currency"
    )
    resolved_candidate_currency = _normalize_contract_currency(
        rate_candidate_currency or effective["rate_candidate_currency"],
        "rate_candidate_currency",
    )
    if currency is not None and resolved_client_currency != legacy_currency:
        _raise_currency_conflict(["rate_client_currency"])

    if framework_contract_id:
        fc = await db.scalar(
            select(ClientFrameworkContract).where(
                ClientFrameworkContract.id == framework_contract_id,
                ClientFrameworkContract.client_id == client_id,
            )
        )
        if fc is None:
            raise HTTPException(400, detail="Invalid framework_contract_id")

    total_dec: Optional[Decimal] = None
    if total_value:
        try:
            total_dec = Decimal(total_value)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(400, detail="Invalid total_value") from exc

    # Plik zapisujemy DOPIERO po nadaniu Orderowi id (flush niżej) — wcześniej
    # leciało tu `order_id=0`, więc każdy PO z tej ścieżki lądował w jednym
    # wspólnym katalogu `client_orders/0/` zamiast w katalogu swojego
    # zamówienia. Rozmiar sprawdzamy PRZED zapisem na dysk, żeby odrzucony
    # upload nie zostawiał sieroty do posprzątania.
    payload_bytes: Optional[bytes] = None
    content_type: Optional[str] = None
    filename: Optional[str] = None
    if file is not None:
        filename = file.filename or "po.pdf"
        if not filename.lower().endswith(_ALLOWED_EXT):
            raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")
        content_type = file.content_type
        payload_bytes = await _read_upload_within_limit(file)

    order = ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        contract=contract,
        job_id=job_id,
        framework_contract_id=framework_contract_id,
        title=title,
        description=description,
        order_type=order_type.value,
        status=order_status,
        # PR 6 (plan analytics): fakt pierwszej aktywacji — nie estymata.
        filled_at=(
            datetime.now(timezone.utc)
            if order_status == ClientOrderStatus.active
            else None
        ),
        start_date=start_date,
        end_date=end_date,
        rate_candidate=resolved_candidate_rate,
        rate_client=resolved_client_rate,
        rate_unit=resolved_unit,
        billing_hours_per_month=resolved_billing_hours,
        total_value=total_dec,
        currency=resolved_client_currency,
        rate_client_currency=resolved_client_currency,
        rate_candidate_currency=resolved_candidate_currency,
        project_part=project_part,
        created_by_user_id=user.id,
        notes=notes,
    )
    db.add(order)
    if order_type == OrderType.md:
        _apply_md_order_quantity(order, md_quantity)
        # Autorytatywne przeliczenie pozostałości JEST tu zbędne i celowo go
        # nie ma: nowe zamówienie nie ma jeszcze ani jednego wiersza zużycia,
        # więc ``md_remaining`` ustawione przez helper to już wartość końcowa,
        # a ``recompute_remaining`` wymagałaby wcześniejszego flushu — czyli
        # INSERT-u wiersza, który musi PRZEJŚĆ CHECK spójności budżetu.
        # (Ścieżka PATCH przelicza pozostałość, bo tam zużycie już istnieje.)
    elif md_quantity is not None:
        raise HTTPException(422, detail="Budżet MD dotyczy tylko zamówienia typu MD")
    if payload_bytes is not None:
        # flush → order.id istnieje, więc plik trafia do katalogu tego Orderu.
        await db.flush()
        _attach_po_bytes(
            order,
            payload=payload_bytes,
            filename=filename or "po.pdf",
            content_type=content_type,
            user=user,
        )
    # Formularz może świadomie zacząć od draftu i uzupełniać cztery wymagane
    # obszary kolejnymi zapisami. Gdy komplet jest już obecny przy tworzeniu,
    # rekord od razu trafia do „Aktywnych”.
    _activate_complete_draft(order)
    if (
        order.status == ClientOrderStatus.active
        and order_type in (OrderType.cost, OrderType.md)
        and not _order_has_required_activation_data(order)
    ):
        raise HTTPException(
            422,
            detail="Uzupełnij numer, datę startu, obie stawki i budżet wybranego typu",
        )
    # Materializacja obejmuje też tworzenie OD RAZU ze statusem active
    # (domyślna wartość ``order_status`` tego formularza) — nie tylko drogę
    # przez auto-aktywację draftu.
    if order.status == ClientOrderStatus.active:
        await db.flush()
        await _materialize_group_after_activation(db, order, actor_id=user.id)
    contract_revived = await _sync_contract_after_order_extension(
        db, order, contract, actor_id=user.id
    )
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_created",
            user_id=user.id,
            details={
                "contract_id": contract_id,
                "job_id": job_id,
                "title": title,
                "status": order.status.value,
                # Ślad wskrzeszenia kontraktu przez przedłużenie — bez niego
                # przejście `ended → active` widać tylko w osi czasu kontraktu,
                # a przyczyna (dodane zamówienie) zostaje po drugiej stronie.
                "contract_revived": contract_revived,
            },
        )
    )
    await db.flush()
    await db.refresh(order)
    await commit_order_write(db)
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.post(
    "/{client_id}/orders/extract",
    response_model=OrderExtractionResult,
)
async def extract_order_pdf(
    client_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    candidate_id: Optional[int] = Form(None, gt=0),
):
    """„Zczytaj dane z dokumentu" — odczyt pól z PDF/DOCX zamówienia klienta.

    Świadoma akcja użytkownika, ODDZIELONA od zapisu: NIE tworzy Orderu ani nie
    zapisuje pliku — zwraca tylko odczytane pola do wstawienia w formularzu
    (wszystkie edytowalne). ``candidate_id`` jest rozwiązywany do kanonicznego
    imienia i nazwiska po stronie serwera, a następnie wiąże stawkę i MD z
    dokładnie jednym wierszem osoby w zamówieniu wieloosobowym; brak lub
    niejednoznaczność zostawia oba pola puste. Przy jakiejkolwiek niepewności
    ``uncertain=True`` → front pokazuje baner „Sprawdź dane!". Kwoty zredagowane
    dla ról bez VIEW_FINANCE.

    Bramkowane: Delivery Lead lub Admin, plus quota AI
    ``AIFeatureKey.order_parser`` (master → feature → miesięczny limit).
    """
    await _assert_client(db, client_id)

    target_consultant: Optional[str] = None
    target_given_names: Optional[str] = None
    if candidate_id is not None:
        # ``candidate_id`` pochodzi z workflow konsultantów. Bramkujemy go do
        # dowolnej nieanulowanej (również historycznej) umowy osoby u bieżącego
        # klienta ALBO żywej umowy w bazie Nexus. Bez tego sam liczbowy
        # identyfikator pozwalałby przypisać do ekstrakcji osobę spoza zbioru
        # konsultantów.
        # EXISTS nie mnoży wierszy kandydata przy wielu kontraktach i zatrzymuje
        # request przed odczytem pliku/quota AI.
        eligible_contract = exists(
            select(Contract.id).where(
                Contract.candidate_id == Candidate.id,
                or_(
                    and_(
                        Contract.client_id == client_id,
                        Contract.status != ContractStatus.void,
                    ),
                    Contract.status.in_(LIVE_CONTRACT_STATUSES),
                ),
            )
        )
        candidate_identity = (
            await db.execute(
                select(Candidate.name, Candidate.lastname).where(
                    Candidate.id == candidate_id,
                    eligible_contract,
                )
            )
        ).one_or_none()
        if candidate_identity is None:
            raise HTTPException(404, detail="Candidate not found")
        target_given_names = (candidate_identity.name or "").strip()
        target_lastname = (candidate_identity.lastname or "").strip()
        if not target_given_names or not target_lastname:
            raise HTTPException(
                422, detail="Kandydat nie ma imienia i nazwiska do dopasowania"
            )
        target_consultant = f"{target_given_names} {target_lastname}"

    filename = file.filename or "zamowienie.pdf"
    ext = os.path.splitext(filename)[1].lower()
    if ext not in _ALLOWED_EXT:
        raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")

    payload = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, detail="File too large")
    if not payload:
        raise HTTPException(400, detail="Pusty plik")

    tmp_path: Optional[str] = None
    try:
        with tempfile.NamedTemporaryFile(
            suffix=ext, delete=False, prefix="nexus_order_"
        ) as tmp:
            tmp.write(payload)
            tmp_path = tmp.name
        try:
            # Ekstrakcja PDF/DOCX (+ OCR) jest synchroniczna i CPU/IO-heavy —
            # offload żeby nie blokować single-worker event loopu.
            text = await run_in_threadpool(extract_text, tmp_path, filename)
        except UnsupportedCvFormat as exc:
            raise HTTPException(400, detail=str(exc)) from exc
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    if not text.strip():
        raise HTTPException(
            400,
            detail=(
                "Nie udało się odczytać tekstu z dokumentu "
                "(skan, plik zaszyfrowany lub nieobsługiwany format .doc?)."
            ),
        )

    # Które reguły klientowe obowiązują i jak kształtują wywołanie parsera —
    # patrz ``app.services.order_policies``. Dwa wpływy na SAMO parsowanie:
    #  - dokument jednoosobowy bez nazwiska (BNP): parser dostaje sam tekst,
    #    bo fail-closed matcher nie miałby czego dopasować i KAŻDY odczyt
    #    kończyłby się wyczyszczeniem stawki i liczby MD;
    #  - domyślna jednostka stawki (PFRON, Erste: zawsze godzinowo), podana
    #    matcherowi już przy parsowaniu — inaczej wyczyściłby poprawną kwotę,
    #    gdy model odczytał wiersz osoby, ale pominął sam token jednostki.
    policies = active_policies(client_id)
    plan = parse_plan(policies)
    text = prepare_document_text(text, policies)

    # Bramka kwoty MUSI obejmować wywołanie modelu: `ai_feature` deklaruje
    # kontekst tylko na czas swojego bloku, a bez deklaracji `parse_order_document`
    # dolatywałby do granicy dostawcy jako niezadeklarowany.
    try:
        async with ai_feature(db, AIFeatureKey.order_parser, user_id=user.id):
            await db.commit()
            extraction = await _extract_with_plan(
                prepare_parser_text(text, policies),
                plan=plan,
                target_consultant=target_consultant,
                target_given_names=target_given_names,
            )
    except AIQuotaExceeded as exc:
        await db.rollback()
        raise HTTPException(
            status_code=503,
            detail={
                "feature": exc.feature.value,
                "reason": exc.reason,
                "used": exc.used,
                "limit": exc.limit,
            },
        ) from exc

    extraction, applied_policies = apply_policies(
        extraction,
        PolicyContext(
            document_text=text,
            target_consultant=target_consultant,
            target_given_names=target_given_names,
            filename=filename,
        ),
        policies,
    )

    extraction = apply_rate_kind(extraction, text, policies)

    # Polityki mogą przeliczyć pole potwierdzone przez matcher (np. brutto→netto),
    # ale nie mogą utworzyć stawki/MD bez dowodu z wiersza tej osoby. U BNP nie
    # ma wierszy do dopasowania — cały dokument JEST pozycją jednej osoby —
    # więc bramka jest tam pominięta świadomie, a nie przez przeoczenie.
    if target_consultant and not plan.single_consultant_document:
        extraction = enforce_consultant_policy_safety(extraction)

    # Finance redaction — kwoty widzą tylko role z VIEW_FINANCE (spójne z
    # _order_response_for_user). Redagujemy NIE TYLKO wartości pól, ale też
    # kanały poboczne, które zdradzałyby sygnał finansowy roli bez VIEW_FINANCE:
    #  - fields_confidence z kluczami finansowymi (np. {"rate_client": 0.97})
    #    ujawnia, że PO zawiera stawkę i jak pewnie ją odczytano;
    #  - uncertain_reasons to tekst (regułowy „Niepewny odczyt: stawka…" ORAZ
    #    swobodny od Claude), który może cytować kwoty.
    # Baner „Sprawdź dane!" zostaje (flaga uncertain), ale z ogólnym powodem.
    # Bramka MUSI być tą samą zmienną co przy kwotach — dwa niezależne
    # sprawdzenia dałyby stan, w którym przypisany DL widzi stawkę, ale nie
    # pewność jej odczytu (albo odwrotnie).
    show_finance = _order_finance_visible(
        user,
        can_finance=_can_manage_order_finance(
            user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
        ),
    )
    if show_finance:
        reasons = extraction.uncertain_reasons
        confidence = extraction.confidence
    else:
        reasons = (
            ["Sprawdź odczytane dane przed zapisem."] if extraction.uncertain else []
        )
        confidence = {
            k: v
            for k, v in extraction.confidence.items()
            if k not in _EXTRACTION_FINANCE_CONF_KEYS
        }

    return OrderExtractionResult(
        title=extraction.title,
        start_date=extraction.start_date,
        end_date=extraction.end_date,
        rate_client=extraction.rate_client if show_finance else None,
        rate_unit=extraction.rate_unit if show_finance else None,
        # Oryginalna stawka MD (polityka BP) to kwota — redagowana jak stawka.
        rate_client_md=extraction.rate_client_md if show_finance else None,
        # Oryginał brutto (polityka Erste) — również kwota, również redagowany.
        rate_client_gross=extraction.rate_client_gross if show_finance else None,
        total_value=extraction.total_value if show_finance else None,
        currency=extraction.currency if show_finance else None,
        # Liczba MD jedzie NIEZREDAGOWANA — jest operacyjna, nie finansowa.
        md_total=extraction.md_total,
        uncertain=extraction.uncertain,
        uncertain_reasons=reasons,
        fields_confidence=confidence,
        # Numer nie jest kwotą — flaga przeżywa redakcję finansową.
        title_needs_review=extraction.title_needs_review,
        # ID konsultanta (BNP) też nie jest kwotą — służy potwierdzeniu
        # tożsamości osoby, więc musi dotrzeć także do ról bez VIEW_FINANCE.
        consultant_ref=extraction.consultant_ref,
        # Nazwa reguły klientowej też nie jest kwotą; `None` znaczy „ten klient
        # nie ma jeszcze własnych reguł", a nie „odczyt się nie udał".
        client_policy=" + ".join(applied_policies) or None,
        source=extraction.source,
    )


@router.patch("/{client_id}/orders/{order_id}", response_model=ClientOrderRead)
async def update_order(
    client_id: int,
    order_id: int,
    payload: ClientOrderUpdate,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    _assert_order_finance_write_allowed(
        user, payload.model_fields_set, can_finance=can_finance
    )
    order = await db.scalar(
        select(ClientOrder)
        # Eager-load jak w get_order — _order_to_read czyta order.contract,
        # a lazy-load na async sesji = MissingGreenlet (500).
        #
        # Harmonogram kandydata jest potrzebny bramce aktywacji jako fallback
        # podczas rolling deploymentu dla wierszy bez snapshotu kosztu.
        .options(
            selectinload(ClientOrder.contract).selectinload(
                Contract.candidate_rate_schedule
            )
        )
        .where(ClientOrder.id == order_id, ClientOrder.client_id == client_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")
    await _assert_no_pending_group_line_offboarding(db, order)

    # PATCH może nieść wyłącznie notatkę, plik albo stawkę. Zachowujemy stan
    # cyklu życia sprzed ``setattr``, żeby taka techniczna edycja istniejącego
    # aktywnego zamówienia nie stała się ukrytym backfillem historycznego
    # ``ended`` Contract. Synchronizacja niżej jest uzasadniona wyłącznie przy
    # wejściu do ``active`` albo rzeczywistej zmianie okresu aktywnego Orderu.
    previous_status = order.status
    previous_start_date = order.start_date
    previous_end_date = order.end_date
    was_active = previous_status == ClientOrderStatus.active
    data = payload.model_dump(exclude_unset=True)
    requested_type = data.pop("order_type", None)
    if "order_type" in payload.model_fields_set:
        if requested_type is None:
            raise HTTPException(422, detail="Typ zamówienia nie może być pusty")
        if order.order_type is None:
            # NULL jest trwałym znacznikiem rekordu sprzed wdrożenia. Nawet
            # stary draft nie może zostać po fakcie sklasyfikowany przez nowy
            # endpoint — historyczne zamówienia mają nadal przechodzić przez
            # klientowe reguły i matchery, bez cichego backfillu przy edycji.
            raise HTTPException(
                409,
                detail="Historyczne zamówienie zachowuje dotychczasowy typ",
            )
        requested_type = OrderType(requested_type)
        _assert_allowed_order_type(client_id, requested_type)
        requested_value = requested_type.value
        if (
            order.status != ClientOrderStatus.draft or order.order_group_id is not None
        ) and order.order_type != requested_value:
            raise HTTPException(
                409,
                detail="Typ można zmienić tylko przed aktywacją zamówienia",
            )
        if order.order_type != requested_value:
            if requested_type != OrderType.cost:
                order.total_value = None
            if requested_type != OrderType.md:
                order.md_input_mode = None
                order.md_input_value = None
                order.md_total = None
                order.md_remaining = None
                order.md_manual_adjustment = Decimal("0")
            order.order_type = requested_value
    # Obie stawki są snapshotem TEGO zamówienia. Ręczna korekta nie może już
    # przepisywać Contract ani sąsiednich zamówień tej osoby.
    if "rate_unit" in payload.model_fields_set:
        new_unit = data.get("rate_unit")
        if new_unit is None:
            raise HTTPException(422, detail="Jednostka stawki nie może być pusta")
        old_unit = order.rate_unit or (
            order.contract.rate_unit if order.contract else RateUnit.monthly
        )
        if new_unit != old_unit:
            if "rate_candidate" not in payload.model_fields_set:
                data["rate_candidate"] = convert_order_rate(
                    order.rate_candidate,
                    old_unit,
                    new_unit,
                    order.billing_hours_per_month or 160,
                )
            if "rate_client" not in payload.model_fields_set:
                data["rate_client"] = convert_order_rate(
                    order.rate_client,
                    old_unit,
                    new_unit,
                    order.billing_hours_per_month or 160,
                )

    legacy_sent = "currency" in payload.model_fields_set
    client_currency_sent = "rate_client_currency" in payload.model_fields_set
    candidate_currency_sent = "rate_candidate_currency" in payload.model_fields_set
    if legacy_sent:
        legacy_currency = _normalize_contract_currency(data.get("currency"), "currency")
        if client_currency_sent:
            client_currency = _normalize_contract_currency(
                data.get("rate_client_currency"), "rate_client_currency"
            )
            if client_currency != legacy_currency:
                _raise_currency_conflict(["rate_client_currency"])
        data["currency"] = legacy_currency
        data["rate_client_currency"] = legacy_currency
    elif client_currency_sent:
        client_currency = _normalize_contract_currency(
            data.get("rate_client_currency"), "rate_client_currency"
        )
        data["rate_client_currency"] = client_currency
        data["currency"] = client_currency
    if candidate_currency_sent:
        data["rate_candidate_currency"] = _normalize_contract_currency(
            data.get("rate_candidate_currency"), "rate_candidate_currency"
        )
    # Klucze obce lecą przez ślepy ``setattr`` niżej, więc nieistniejąca
    # rekrutacja albo umowa ramowa kończyła się ForeignKeyViolationError przy
    # commicie — czyli 500 bez CORS („Network Error"), zamiast odmowy, którą
    # da się przeczytać. ``create_order_extension`` sprawdza umowę ramową od
    # początku; PATCH tej pary nie miał. Oba pola muszą też należeć do TEGO
    # klienta — samo istnienie wiersza pozwalałoby podpiąć cudzą rekrutację.
    #
    # 422, nie 400: to jest walidacja PAYLOADU, a każda inna bramka w tym
    # handlerze (typ zamówienia, część umowy, liczba MD, komplet pól do
    # aktywacji) odpowiada 422. ``create_order_extension`` zwraca dla umowy
    # ramowej 400 i tak ZOSTAJE — zmiana statusu na istniejącym endpointcie
    # jest zmianą kontraktu API, której ten ticket nie dotyczy.
    if data.get("framework_contract_id") is not None:
        framework_ok = await db.scalar(
            select(ClientFrameworkContract.id).where(
                ClientFrameworkContract.id == data["framework_contract_id"],
                ClientFrameworkContract.client_id == client_id,
            )
        )
        if framework_ok is None:
            raise HTTPException(
                422,
                detail=(
                    "Wskazana umowa ramowa nie istnieje albo należy do innego "
                    "klienta (framework_contract_id)."
                ),
            )
    if data.get("job_id") is not None:
        job_ok = await db.scalar(
            select(Job.id).where(
                Job.id == data["job_id"],
                Job.client_id == client_id,
            )
        )
        if job_ok is None:
            raise HTTPException(
                422,
                detail=(
                    "Wskazana rekrutacja nie istnieje albo należy do innego "
                    "klienta (job_id)."
                ),
            )
    if "project_part" in data:
        # Edycja/uzupełnienie draftu: wartość ze słownika albo NULL; u klientów
        # innych niż e-Zdrowie pole pozostaje zabronione (ticket #3).
        try:
            data["project_part"] = validate_project_part(
                client_id, data["project_part"], require=False
            )
        except ValueError as e:
            raise HTTPException(422, detail=str(e)) from None
    # „Liczba MD zamówienia" nie jest kolumną — schodzi z pętli setattr i ma
    # własną walidację. Stosowana PO zwykłych polach, żeby PATCH niosący
    # stawkę przychodową i liczbę MD w jednym żądaniu widział już nową stawkę.
    md_quantity = data.pop("md_quantity", None)
    for field, value in data.items():
        setattr(order, field, value)
    if "md_quantity" in payload.model_fields_set:
        _apply_md_order_quantity(order, md_quantity)
        await recompute_remaining(db, order)
    _refresh_md_rate_mirror(order, explicit_fields=payload.model_fields_set)

    auto_activated = _auto_activate_unless_status_explicit(
        order, explicit_fields=payload.model_fields_set
    )
    if auto_activated:
        data["status"] = ClientOrderStatus.active

    # PR 6 (plan analytics): pierwsze przejście na active stempluje filled_at
    # (fakt, ustawiany RAZ — kolejne pauzy/reaktywacje go nie ruszają).
    if (
        order.status == ClientOrderStatus.active
        and order.filled_at is None
        and "status" in data
    ):
        order.filled_at = datetime.now(timezone.utc)

    # Materializacja po KAŻDEJ drodze do statusu active — także po jawnym
    # ``PATCH {"status": "active"}``. Sama auto-aktywacja nie wystarcza:
    # jawna aktywacja u klienta MD tworzyłaby aktywne zamówienie-widmo,
    # niewidoczne ani w rejestrze grup, ani w zakładce Draft (status ≠ draft)
    # — dokładnie klasa awarii z ticketu. Poza swoim zakresem (klient
    # nie-MD, wiersz w grupie, tytuł-placeholder) serwis jest no-opem.
    if order.status == ClientOrderStatus.active and order.order_group_id is None:
        effective_type = effective_standalone_order_type(
            order.client_id, order.order_type
        )
        try:
            process_active_type = should_process_active_standalone_order(
                client_id, effective_type, was_active=was_active
            )
        except ValueError as exc:
            raise HTTPException(422, detail=str(exc)) from exc
        if process_active_type:
            if effective_type in (OrderType.cost, OrderType.md) and not (
                _order_has_required_activation_data(order)
            ):
                raise HTTPException(
                    422,
                    detail=(
                        "Uzupełnij numer, datę startu, obie stawki i budżet wybranego typu"
                    ),
                )
            await _materialize_group_after_activation(db, order, actor_id=user.id)

    # PATCH jest osobną ścieżką wejścia do ``active``: widok inline najpierw
    # zakłada niepełny draft, a kolejne zapisy uzupełniają numer/okres/stawki.
    # Do tej pory tylko POST „Dodaj przedłużenie" wołał synchronizację, więc
    # dokładnie ten zwykły flow zostawiał kontrakt ``ended`` mimo żywego
    # zamówienia. Już aktywny Order woła ją ponownie tylko po realnej zmianie
    # okresu; notes/title/rate-only PATCH nie może po cichu naprawiać rekordów,
    # które migracja 0250 celowo zostawiła audit-only. Sam serwis pozostaje
    # idempotentnym no-opem dla przyszłego okresu i innych statusów Contract.
    contract_revived = False
    patch_requires_contract_sync = _patch_requires_contract_sync(
        order,
        previous_status=previous_status,
        previous_start_date=previous_start_date,
        previous_end_date=previous_end_date,
    )
    if order.contract is not None and patch_requires_contract_sync:
        contract_revived = await _sync_contract_after_order_extension(
            db, order, order.contract, actor_id=user.id
        )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_updated",
            user_id=user.id,
            details={
                "order_id": order_id,
                "changed": sorted(payload.model_fields_set),
                "auto_activated": auto_activated,
                "contract_revived": contract_revived,
            },
        )
    )
    await commit_order_write(db)
    await db.refresh(order)
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.post(
    "/{client_id}/orders/{order_id}/close",
    response_model=ClientOrderRead,
)
async def close_order(
    client_id: int,
    order_id: int,
    payload: ClientOrderClose,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Zakończ JEDNO zamówienie — bez dotykania umowy i pozostałych zamówień.

    Do sierpnia 2026 jedyną drogą „zakończenia zamówienia" z karty kontraktora
    było wypowiedzenie CAŁEJ umowy (``POST /api/contracts/{id}/terminate``), a
    ono domyka wszystkie zamówienia tego kontraktu — także linię rozliczaną
    w MD, która opisuje zupełnie inną, trwającą współpracę. Stąd zgłoszenie
    „zakończenie zamówienia okresowego skasowało zamówienie MD".

    Zakres jest wąski i to jest cała jego wartość: zmienia się data końca
    i status TEGO wiersza. Umowa (``Contract.status``/``end_date``) zostaje
    nietknięta — jej zakończenie jest osobną decyzją z własnym powodem
    i audytem.

    Linie zamówień grupowych są odrzucane (409): grupa ma własne
    zakończenie (``POST /order-groups/{id}/close``), które prowadzi budżet,
    historię i sprawy offboardingowe. Dwie drogi do jednego wiersza rozjechałyby
    się przy pierwszej zmianie którejkolwiek.

    Data WSTECZ jest dozwolona i to jest świadome — tak samo jak w
    ``/contracts/{id}/terminate`` i w zakończeniu grupy. Zamówienia domyka się
    nagminnie po fakcie (dokument od klienta przychodzi z opóźnieniem), a jedyne
    ograniczenie z sensem biznesowym to początek samego zamówienia. Rekordy
    historyczne często nie mają ``start_date`` i wtedy nie ma się do czego
    odnieść — sztywny limit „nie dalej niż rok wstecz" byłby regułą, której
    nikt nie ustalił, a która zablokowałaby porządkowanie starych danych.
    """

    await _assert_client(db, client_id)
    order = await db.scalar(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract))
        .where(ClientOrder.id == order_id, ClientOrder.client_id == client_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")
    if order.order_group_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "order_belongs_to_group",
                "message": (
                    "To jest linia zamówienia grupowego — zakończ ją przez "
                    "zamówienie, do którego należy."
                ),
                "order_group_id": order.order_group_id,
            },
        )
    if order.status in (ClientOrderStatus.completed, ClientOrderStatus.cancelled):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "code": "order_already_closed",
                "message": "To zamówienie jest już zakończone.",
                "status": order.status.value,
            },
        )
    if order.start_date is not None and payload.closure_date < order.start_date:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "Data zakończenia jest wcześniejsza niż początek zamówienia "
                f"({order.start_date.isoformat()})."
            ),
        )

    # Lustro `close_order_group` i syncu terminacji umowy: data zapisuje się
    # zawsze, ale status `completed` dostaje wyłącznie zamówienie, którego
    # dzień zakończenia już nadszedł. Zakończenie zaplanowane na przyszłość nie
    # może wyłączyć zamówienia, które dziś jeszcze obowiązuje — resztę
    # materializuje dzienny `dl_portal_expiry_scanner`.
    today = business_today()
    if order.end_date is None or order.end_date > payload.closure_date:
        order.end_date = payload.closure_date
    if payload.closure_date <= today:
        order.status = ClientOrderStatus.completed

    db.add(
        Activity(
            entity_type="client_order",
            entity_id=order.id,
            action="order_closed",
            user_id=user.id,
            details={
                "client_id": client_id,
                "contract_id": order.contract_id,
                "closure_date": payload.closure_date.isoformat(),
                "closure_reason": payload.closure_reason,
                "status": order.status.value,
            },
        )
    )
    # `flush` + `refresh` PRZED commitem — tak jak na ścieżce tworzenia
    # zamówienia. `updated_at` ma serwerowy `onupdate`, więc po UPDATE atrybut
    # jest wygasły niezależnie od `expire_on_commit=False`; sięgnięcie po niego
    # przy budowaniu odpowiedzi to w sesji async `MissingGreenlet`, czyli 500
    # bez nagłówków CORS (w przeglądarce „Network Error" bez wskazówki).
    await db.flush()
    await db.refresh(order)
    await commit_order_write(db)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.delete("/{client_id}/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    client_id: int,
    order_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft cancel: status=cancelled. Hard delete tylko gdy status=draft."""
    await _assert_client(db, client_id)
    order = await db.scalar(
        select(ClientOrder)
        .where(ClientOrder.id == order_id, ClientOrder.client_id == client_id)
        .with_for_update()
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")
    await _assert_no_pending_group_line_offboarding(db, order)

    if order.status == ClientOrderStatus.draft:
        if order.file_path:
            storage_service.delete_client_order_po(order.file_path)
        await db.delete(order)
    else:
        order.status = ClientOrderStatus.cancelled

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_cancelled",
            user_id=user.id,
            details={"order_id": order_id},
        )
    )
    await commit_order_write(db)


# ── PO file ─────────────────────────────────────────────────────────────────


@router.get("/{client_id}/orders/{order_id}/file")
async def download_order_po(
    client_id: int,
    order_id: int,
    user: UnifiedOrderExportReader,
    db: AsyncSession = Depends(get_db),
):
    await _require_order_file_read(db, user, client_id)
    order = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if order is None or order.file_path is None:
        raise HTTPException(404, detail="File not found")
    abs_path = storage_service.get_client_order_po_path(order.file_path)
    return FileResponse(
        path=str(abs_path),
        filename=order.filename or "po.pdf",
        media_type=order.content_type or "application/pdf",
    )


# ── Order documents (jeden plik, dwa widoki: kontrakt + osoba) ──────────────
# Wymaganie: załączony PDF zamówienia ma być widoczny w Dokumentach kontraktu
# ORAZ w Plikach osoby — jako JEDEN zapisany plik, do którego oba widoki się
# odwołują (nie kopia). Realizacja read-time: plik żyje na ``ClientOrder.file_path``
# i jest pobierany istniejącym ``GET /orders/{id}/file``; poniższe endpointy tylko
# LISTUJĄ te pliki dla kontraktu / osoby. Zero kopii, zero migracji dokumentów.


def _order_to_document_item(order: ClientOrder) -> OrderDocumentItem:
    # `file_uploader` musi być eager-loadowany przez wywołującego — lazy-load
    # relacji na sesji async to MissingGreenlet (500 bez CORS), a nie None.
    uploader = order.file_uploader
    return OrderDocumentItem(
        order_id=order.id,
        client_id=order.client_id,
        contract_id=order.contract_id,
        title=order.title,
        filename=order.filename,
        content_type=order.content_type,
        size_bytes=order.size_bytes,
        created_at=order.created_at,
        order_status=order.status,
        uploaded_by_email=uploader.email if uploader else None,
        uploaded_at=order.file_uploaded_at,
    )


@router.get(
    "/order-documents/by-contract/{contract_id}",
    response_model=OrderDocumentsResponse,
)
async def list_contract_order_documents(
    contract_id: int,
    user: UnifiedOrderExportReader,
    db: AsyncSession = Depends(get_db),
):
    """PO PDF-y zamówień danego kontraktu — sekcja „Dokumenty zamówień" w
    zakładce Dokumenty kontraktu. Read-only widok tego samego pliku, pobierany
    istniejącym ``GET /orders/{id}/file`` (nie kopiuje pliku)."""
    contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(404, detail="Contract not found")
    await _require_order_file_read(db, user, contract.client_id)

    orders = (
        (
            await db.execute(
                select(ClientOrder)
                .options(selectinload(ClientOrder.file_uploader))
                .where(
                    ClientOrder.contract_id == contract_id,
                    ClientOrder.file_path.is_not(None),
                )
                .order_by(ClientOrder.created_at.desc())
            )
        )
        .scalars()
        .all()
    )
    return OrderDocumentsResponse(
        documents=[_order_to_document_item(o) for o in orders]
    )


@router.get(
    "/order-documents/by-candidate/{candidate_id}",
    response_model=OrderDocumentsResponse,
)
async def list_candidate_order_documents(
    candidate_id: int,
    user: UnifiedOrderExportReader,
    db: AsyncSession = Depends(get_db),
):
    """PO PDF-y wszystkich zamówień osoby/kontraktora — sekcja „Dokumenty
    zamówień / kontraktów" w Plikach osoby. Ten sam plik co w widoku kontraktu.

    Poufność: PO zawiera stawki, więc filtrujemy po dostępie do klienta —
    pokazujemy tylko zamówienia klientów, których użytkownik może czytać
    (admin/Finance = wszystkie, Delivery Lead = przypisane). Spójne
    z ``_require_client_order_read``. Osoby może dotyczyć wielu klientów."""
    exists = await db.scalar(select(Candidate.id).where(Candidate.id == candidate_id))
    if exists is None:
        raise HTTPException(404, detail="Candidate not found")

    orders = (
        (
            await db.execute(
                select(ClientOrder)
                .options(selectinload(ClientOrder.file_uploader))
                .join(Contract, Contract.id == ClientOrder.contract_id)
                .where(
                    Contract.candidate_id == candidate_id,
                    ClientOrder.file_path.is_not(None),
                )
                .order_by(ClientOrder.created_at.desc())
            )
        )
        .scalars()
        .all()
    )

    access_cache: dict[int, bool] = {}
    visible: list[OrderDocumentItem] = []
    for o in orders:
        can = access_cache.get(o.client_id)
        if can is None:
            can = await _can_read_order_file(db, user, o.client_id)
            access_cache[o.client_id] = can
        if can:
            visible.append(_order_to_document_item(o))
    return OrderDocumentsResponse(documents=visible)


# ── Flow B: atomic create Contract + Order ─────────────────────────────────


@router.post(
    "/{client_id}/contract-with-order",
    response_model=NewContractorOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_contract_with_order(
    client_id: int,
    payload: NewContractorOrderRequest,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Flow B — "Nowy kontraktor / zamówienie": atomic Contract + Order create."""
    await _assert_client(db, client_id)
    _assert_allowed_order_type(client_id, payload.order_type)
    if payload.order_type != OrderType.periodic:
        raise HTTPException(
            422,
            detail=(
                "Nowego kontraktora zakłada formularz okresowy. Zamówienie "
                "kosztowe lub MD utwórz jako grupę i dodaj konsultanta."
            ),
        )
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    contract_finance_kwargs, order_finance_kwargs = _flow_b_finance_kwargs(
        payload, user, can_finance=can_finance
    )

    # Jednostka stawki NIE jest już twardo `monthly`. Jeśli wywołujący ją podał
    # (tylko rola finansowa — operacyjną odsiewa `_assert_order_finance_write_allowed`),
    # respektujemy wybór (także `monthly`, gdy ktoś świadomie go zaznaczył).
    # W przeciwnym razie bierzemy jednostkę najczęstszą u tego klienta — również
    # dla rekordu czysto operacyjnego bez stawek.
    if payload.rate_unit is not None:
        try:
            resolved_rate_unit = RateUnit(payload.rate_unit)
        except ValueError:
            raise HTTPException(400, detail="Invalid rate_unit") from None
    else:
        resolved_rate_unit = await default_rate_unit_for_client(db, client_id)

    cand = await db.scalar(
        select(Candidate).where(Candidate.id == payload.candidate_id)
    )
    if cand is None:
        raise HTTPException(404, detail="Candidate not found")

    if payload.job_id is not None:
        job = await db.scalar(
            select(Job).where(Job.id == payload.job_id, Job.client_id == client_id)
        )
        if job is None:
            raise HTTPException(
                400, detail="job_id must be a Job belonging to this client"
            )

    if payload.framework_contract_id is not None:
        fc = await db.scalar(
            select(ClientFrameworkContract).where(
                ClientFrameworkContract.id == payload.framework_contract_id,
                ClientFrameworkContract.client_id == client_id,
            )
        )
        if fc is None:
            raise HTTPException(400, detail="Invalid framework_contract_id")

    contract = Contract(
        candidate_id=payload.candidate_id,
        client_id=client_id,
        job_id=payload.job_id,
        start_date=payload.contract_start_date,
        end_date=payload.contract_end_date,
        # Flow B collects only a subset of activation fields (it has no
        # contract_type/work_mode at all), so neither Admin nor an operational
        # role may bypass the canonical contract lifecycle. Activation belongs
        # exclusively to contract_lifecycle.activate_contract(), which validates
        # the complete draft and signed evidence when required.
        status=ContractStatus.draft,
        handover_notes=payload.notes,
        rate_unit=resolved_rate_unit,
        **contract_finance_kwargs,
    )
    db.add(contract)
    await db.flush()  # Get contract.id

    # „Część umowy" — wymagana dla Centrum e-Zdrowia, zabroniona u innych
    # (ticket #3, bramka po client_id).
    try:
        order_project_part = validate_project_part(
            client_id, payload.project_part, require=True
        )
    except ValueError as e:
        raise HTTPException(422, detail=str(e)) from None

    order = ClientOrder(
        client_id=client_id,
        contract_id=contract.id,
        contract=contract,
        job_id=payload.job_id,
        framework_contract_id=payload.framework_contract_id,
        title=payload.title,
        order_type=payload.order_type.value,
        status=ClientOrderStatus.draft,
        # PR 6: the activation fact is stamped only by the explicit order
        # status transition, never by an incomplete atomic create.
        filled_at=None,
        start_date=payload.order_start_date,
        end_date=payload.order_end_date,
        created_by_user_id=user.id,
        notes=payload.notes,
        project_part=order_project_part,
        rate_unit=resolved_rate_unit,
        **order_finance_kwargs,
    )
    db.add(order)
    # To samo kryterium co przy późniejszym „Uzupełnij zamówienie": jeżeli
    # formularz atomowy już niesie numer, obie stawki i pełny okres, Order nie
    # powinien zaliczać zbędnego przystanku w zakładce Draft. Kontrakt zachowuje
    # własny, niezależny i bardziej rygorystyczny lifecycle podpisu.
    _activate_complete_draft(order)
    if order.status == ClientOrderStatus.active:
        await db.flush()
        await _materialize_group_after_activation(db, order, actor_id=user.id)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="contract_with_order_created",
            user_id=user.id,
            details={
                "candidate_id": payload.candidate_id,
                "job_id": payload.job_id,
                "contract_id": contract.id,
            },
        )
    )

    await db.flush()
    await db.refresh(order)
    await commit_order_write(db)

    # Callers without finance access never receive a computed/inferred value.
    monthly_margin: Optional[Decimal | int] = None
    if can_finance:
        # Umowa powstała przed chwilą w tym żądaniu, więc jej harmonogramy
        # stawek nie są wczytane — a `effective_rate_fields` sięga po nie
        # atrybutem i lazy-load na sesji async to `MissingGreenlet` (500 bez
        # CORS). Jedno dociągnięcie po commicie zamyka tę krawędź; wiersze
        # harmonogramu i tak są tu puste, więc resolver zejdzie do kolumn.
        priced = await db.scalar(
            select(Contract)
            .options(*RATE_SCHEDULE_LOADS)
            .where(Contract.id == contract.id)
        )
        if priced is not None:
            monthly_margin = _compute_monthly_margin(order, priced)

    return NewContractorOrderResponse(
        contract_id=contract.id,
        order_id=order.id,
        candidate_name=cand.name,
        monthly_margin=monthly_margin,
    )


# ── Update PO file ──────────────────────────────────────────────────────────


@router.put("/{client_id}/orders/{order_id}/file", response_model=ClientOrderRead)
async def replace_order_po(
    client_id: int,
    order_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """Wgraj/podmień PDF zamówienia.

    Podmiana jest w miejscu: jeden Order = jeden plik, a sekcja „Dokumenty
    zamówień" w zakładce Dokumenty kontraktu czyta dokładnie ten wiersz. Nowa
    wersja więc AKTUALIZUJE tam pozycję zamiast ją dublować — nie ma drugiego
    zapisu, który mógłby się rozjechać.

    Tylko PDF, w odróżnieniu od Flow A („Dodaj przedłużenie"), które przyjmuje
    też DOCX. Zawężenie dotyczy WYŁĄCZNIE tej ścieżki: globalne zamknęłoby
    działającą od dawna ścieżkę przedłużeń, gdzie klienci przysyłają PO również
    w Wordzie.
    """
    await _assert_client(db, client_id)
    await _require_order_file_read(db, user, client_id)
    order = await db.scalar(
        select(ClientOrder)
        .options(selectinload(ClientOrder.contract))
        .where(ClientOrder.id == order_id, ClientOrder.client_id == client_id)
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")

    filename = file.filename or "po.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(415, detail="Tylko pliki PDF")

    replaced = order.file_path is not None
    payload_bytes = await _read_upload_within_limit(file)
    # Rozszerzenie deklaruje nadawca, nagłówek pliku nie. Bez tej kontroli
    # dowolne bajty przemianowane na „.pdf" trafiały na wolumen i były potem
    # serwowane z `media_type=application/pdf` każdemu, kto otworzy dokument.
    if not payload_bytes.startswith(b"%PDF-"):
        raise HTTPException(415, detail="Plik nie jest dokumentem PDF.")
    superseded_path = _attach_po_bytes(
        order,
        payload=payload_bytes,
        filename=filename,
        content_type=file.content_type,
        user=user,
    )

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_file_uploaded",
            user_id=user.id,
            details={
                "order_id": order_id,
                "filename": filename,
                "replaced": replaced,
            },
        )
    )
    await commit_order_write(db)
    # Stary blob zwalniamy DOPIERO gdy nowy wiersz jest utrwalony. Przy
    # nieudanym commicie zostaje osierocony plik (do posprzątania), a nie baza
    # wskazująca na dokument, którego już nie ma.
    if superseded_path:
        storage_service.delete_client_order_po(superseded_path)
    await db.refresh(order)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.delete(
    "/{client_id}/orders/{order_id}/file",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_order_po(
    client_id: int,
    order_id: int,
    user: DeliveryLeadOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Usuń wyłącznie aktualny PDF zamówienia, bez zmiany innych pól."""

    await _assert_client(db, client_id)
    await _require_order_file_read(db, user, client_id)
    order = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")
    if order.file_path is None:
        raise HTTPException(404, detail="File not found")

    previous_path = order.file_path
    previous_filename = order.filename
    order.filename = None
    order.file_path = None
    order.content_type = None
    order.size_bytes = None
    order.file_uploaded_by = None
    order.file_uploaded_at = None
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_file_deleted",
            user_id=user.id,
            details={"order_id": order_id, "filename": previous_filename},
        )
    )
    await commit_order_write(db)
    # Najpierw commit metadanych, potem zwolnienie blobu: awaria dysku nie może
    # cofnąć poprawnego usunięcia z formularza ani zostawić bazy wskazującej na
    # nieistniejący plik.
    storage_service.delete_client_order_po(previous_path)


async def _extract_with_plan(
    text: str,
    *,
    plan,
    target_consultant: Optional[str],
    target_given_names: Optional[str],
):
    """Wywołanie parsera zamówienia w wariancie wynikającym z reguł klienta.

    Wyodrębnione z handlera, bo bramka kwoty musi teraz OBEJMOWAĆ wywołanie
    modelu — a wcięcie czterech gałęzi w `async with` dawałoby diff, w którym
    łatwo pomylić, która gałąź dostaje który zestaw argumentów. Rozróżnienia
    są tu istotne: BNP dostaje sam tekst (fail-closed matcher nie miałby czego
    dopasować), PFRON i Erste dokładają domyślną jednostkę stawki.
    """
    if plan.single_consultant_document:
        return await parse_order_document(text)
    if target_consultant and plan.rate_unit_default:
        return await parse_order_document(
            text,
            consultant_name=target_consultant,
            consultant_given_names=target_given_names,
            consultant_rate_unit_default=plan.rate_unit_default,
        )
    if target_consultant:
        # Nie rozszerzamy kontraktu wywołania parsera dla pozostałych klientów:
        # ich matchery zachowują dotychczasowe, fail-closed zachowanie.
        return await parse_order_document(
            text,
            consultant_name=target_consultant,
            consultant_given_names=target_given_names,
        )
    # Zachowanie formularzy grupy/jednoosobowych pozostaje bez zmian.
    return await parse_order_document(text)
