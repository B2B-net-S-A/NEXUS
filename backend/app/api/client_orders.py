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
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from starlette.concurrency import run_in_threadpool

from app.analytics.capabilities import AnalyticsCapability, user_has_capability
from app.api.deps import DlAssignedOrAdmin, TacPlus
from app.core.database import get_db
from app.core.scheduling import business_today
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.contract_candidate_rate import ContractCandidateRate
from app.models.job import Job
from app.models.user import UserRole
from app.schemas.client_order import (
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
from app.services.ai_quota import AIQuotaExceeded, check_and_increment
from app.services.client_access import deny, resolve_client_access
from app.services.contract_rates import RATE_SCHEDULE_LOADS, effective_rate_fields
from app.services.ezdrowie import validate_project_part
from app.services.cv_text_extractor import UnsupportedCvFormat, extract_text
from app.services.order_pdf_parser import (
    enforce_nordea_order_number,
    parse_order_document,
)
from app.services.order_excel_export import (
    OrderExportRow,
    build_orders_workbook,
    orders_export_filename,
)

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


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
    """Require an explicit DL/TAC relationship for candidate-bearing orders."""

    await _assert_client(db, client_id)
    access = await resolve_client_access(db, user, client_id)
    if not access.can_view_legal_documents:
        raise deny("zamówienia klienta wymagają jawnego przypisania DL/TAC")


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
    order.filename = filename
    order.file_path = rel_path
    order.content_type = content_type
    order.size_bytes = size
    order.file_uploaded_by = user.id
    order.file_uploaded_at = datetime.now(timezone.utc)
    return previous if previous and previous != rel_path else None


def _order_has_required_activation_data(order: ClientOrder) -> bool:
    """Czy draft ma komplet pól wskazanych przez formularz zamówienia.

    Numer zastępczy ``(bez numeru)`` powstaje po pierwszej edycji pojedynczego
    pola i nie jest prawdziwym numerem. „Okres” oznacza obie granice; dzięki
    temu częściowo uzupełniony rekord pozostaje w Draft zamiast przedwcześnie
    trafiać do Aktywnych.
    """

    title = (order.title or "").strip()
    return bool(
        title
        and title != "(bez numeru)"
        and order.start_date is not None
        and order.end_date is not None
        and order.rate_client is not None
        and order.contract is not None
        and order.contract.rate_candidate is not None
    )


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
    if rate_client_effective is None or eff["rate_candidate"] is None:
        return None
    monthly_client = _normalize_monthly(
        rate_client_effective, contract.rate_unit, contract.billing_hours_per_month
    )
    monthly_cand = _normalize_monthly(
        eff["rate_candidate"], contract.rate_unit, contract.billing_hours_per_month
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


# F-13 / P0.12: kwoty (stawki, marża, wartość zamówienia) widzą tylko role z
# VIEW_FINANCE. TAC i Delivery Lead zachowują operacyjny widok zamówień i
# kontraktorów, ale bez kwot — spójne z redakcją w contracts.py
# (`_redact_contract_finance`) i clients.py. Waluta również znika, żeby nie
# zdradzać sposobu rozliczenia ukrytej kwoty.
_ORDER_FINANCE_FIELDS = ("rate_client", "total_value", "monthly_margin", "currency")
# Klucze pól finansowych w fields_confidence odczytu PDF — redagowane dla ról
# bez VIEW_FINANCE (obecność klucza sama zdradza, że PO zawiera stawkę/wartość).
_EXTRACTION_FINANCE_CONF_KEYS = frozenset(
    {"rate_client", "total_value", "currency", "rate_unit"}
)
_CONTRACTOR_FINANCE_FIELDS = (
    "rate_candidate",
    "latest_order_rate_client",
    "latest_order_monthly_margin",
)
_ORDER_FINANCE_WRITE_FIELDS = frozenset(
    {
        "rate_client",
        "rate_candidate",
        "total_value",
        "currency",
        "rate_unit",
        "billing_hours_per_month",
    }
)
# Podzbiór, który wolno zapisać PRZYPISANEMU Delivery Leadowi. Admin ma pełen
# zestaw. Różnica nie jest kosmetyczna: `rate_unit` i `billing_hours_per_month`
# nie są kwotami, tylko REGUŁĄ PRZELICZANIA kwot (`_normalize_monthly` mnoży
# stawkę przez 22 albo przez godziny). Ich zmiana przelicza wstecz KAŻDĄ kwotę
# i marżę na kontrakcie, w tym historyczne — a ticket prosi wyłącznie o dwie
# stawki. Waluta i wartość zamówienia zostają, bo opisują to konkretne
# zamówienie i nie przepisują niczego wstecz.
_DL_ORDER_FINANCE_WRITE_FIELDS = frozenset(
    {"rate_client", "rate_candidate", "total_value", "currency"}
)


async def _dl_assigned_to_client(db: AsyncSession, user, client_id: int) -> bool:
    """Czy ten user ma JAWNE przypisanie Delivery Leada do tego klienta.

    To samo zapytanie co w ``require_dl_assigned_or_admin`` (deps.py), ale
    liczone tutaj i wprost — patrz ``_can_manage_order_finance`` po powód,
    dla którego nie wystarczy „request przeszedł tamten guard".
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
    """Kto widzi i zapisuje kwoty na zamówieniach TEGO klienta.

    Admin zawsze; Delivery Lead WYŁĄCZNIE na kliencie, do którego jest jawnie
    przypisany. To rozszerzenie pierwotnej reguły „tylko admin" (F-13/P0.12):
    DL prowadzi zamówienia klienta na co dzień i to on uzupełnia draft, więc
    odsyłanie każdej stawki do admina zamieniało rejestr w prośbę o czynność,
    której adresat nie mógł wykonać.

    Predykat CELOWO sprawdza rolę i przypisanie niezależnie, zamiast ufać temu,
    że request przeszedł ``DlAssignedOrAdmin``: tamten guard przepuszcza
    ``head_of_recruitment`` GLOBALNIE, bez patrzenia na przypisanie (deps.py).
    Reguła „ktokolwiek przeszedł guard" po cichu dałaby HoR zapis stawek
    u wszystkich klientów. TAC, HoR, recruiter, sourcer: zawsze False.

    Zakres jest lokalny dla tej powierzchni. `contracts.py` zachowuje własną,
    węższą bramkę (admin-only) — tam kwoty jadą w ~20 innych odpowiedziach.
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

    Przypisany Delivery Lead dostaje WĘŻSZY zestaw pól niż admin
    (``_DL_ORDER_FINANCE_WRITE_FIELDS``): kwoty tak, reguły ich przeliczania nie.
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

    try:
        rate_unit = RateUnit(payload.rate_unit or RateUnit.monthly.value)
    except ValueError:
        raise HTTPException(400, detail="Invalid rate_unit") from None

    currency = payload.currency or "PLN"
    billing_hours = payload.billing_hours_per_month or 160
    contract_kwargs: dict[str, object] = {
        "rate_client": payload.rate_client,
        "rate_candidate": payload.rate_candidate,
        "currency": currency,
        "rate_unit": rate_unit,
        "billing_hours_per_month": billing_hours,
    }
    order_kwargs: dict[str, object] = {
        "rate_client": payload.rate_client,
        "total_value": payload.total_value,
        "currency": currency,
    }
    return contract_kwargs, order_kwargs


def _redact_order_finance(order: ClientOrderRead) -> ClientOrderRead:
    for field in _ORDER_FINANCE_FIELDS:
        setattr(order, field, None)
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
        start_date=order.start_date,
        end_date=order.end_date,
        rate_client=order.rate_client,
        total_value=order.total_value,
        currency=order.currency,
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


@router.get("/{client_id}/orders", response_model=ClientOrdersGroupedResponse)
async def list_contractors_with_orders(
    client_id: int,
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca listę kontraktorów (per Contract) z historią Orderów per Contract.

    UI: tab "Zamówienia & Kontrakty" pokazuje listę kart (1 karta = 1 kontraktor).
    """
    await _require_client_order_read(db, user, client_id)

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
            c.client_orders or [],
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
                rate_unit=c.rate_unit.value,
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
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """Export exactly the ordered rows visible in the caller's client view."""

    client = await _assert_client(db, client_id)
    grouped = await list_contractors_with_orders(client_id, user, db)
    by_id: dict[int, tuple[ContractWithOrdersRead, ClientOrderRead]] = {}
    for contractor in grouped.contractors:
        for order in contractor.orders:
            by_id[order.id] = (contractor, order)

    requested = list(dict.fromkeys(payload.order_ids))
    if any(order_id not in by_id for order_id in requested):
        # Do not reveal whether an ID belongs to another client.
        raise HTTPException(404, detail="Nie znaleziono zamówienia u tego klienta")

    rows = [
        OrderExportRow(
            consultant_name=by_id[order_id][0].candidate_name,
            order_number=by_id[order_id][1].title,
            cost_rate=by_id[order_id][0].rate_candidate,
            revenue_rate=by_id[order_id][1].rate_client,
            start_date=by_id[order_id][1].start_date,
            end_date=by_id[order_id][1].end_date,
        )
        for order_id in requested
    ]
    content = await run_in_threadpool(
        build_orders_workbook, rows, include_model_columns=False
    )
    filename = orders_export_filename(client.display_name or client.name)
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
    user: TacPlus,
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
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _require_client_order_read(db, user, client_id)
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
    return result


@router.post(
    "/{client_id}/orders",
    response_model=ClientOrderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_order_extension(
    client_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    contract_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    order_status: ClientOrderStatus = Form(ClientOrderStatus.active),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    rate_client: Optional[Decimal] = Form(None),
    total_value: Optional[str] = Form(None),
    currency: Optional[str] = Form(None),
    framework_contract_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
    project_part: Optional[str] = Form(None),
):
    """Flow A — "Dodaj przedłużenie": tworzy Order pod istniejącym Contract."""
    from decimal import InvalidOperation

    supplied_finance_fields = {
        field
        for field, value in {
            "rate_client": rate_client,
            "total_value": total_value,
            "currency": currency,
        }.items()
        if value is not None
    }
    await _assert_client(db, client_id)
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
        select(Contract).where(
            Contract.id == contract_id, Contract.client_id == client_id
        )
    )
    if contract is None:
        raise HTTPException(
            400, detail="contract_id must reference a Contract of this client"
        )

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
        status=order_status,
        # PR 6 (plan analytics): fakt pierwszej aktywacji — nie estymata.
        filled_at=(
            datetime.now(timezone.utc)
            if order_status == ClientOrderStatus.active
            else None
        ),
        start_date=start_date,
        end_date=end_date,
        rate_client=rate_client,
        total_value=total_dec,
        currency=currency or contract.currency,
        project_part=project_part,
        created_by_user_id=user.id,
        notes=notes,
    )
    db.add(order)
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
            },
        )
    )
    await db.flush()
    await db.refresh(order)
    await db.commit()
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.post(
    "/{client_id}/orders/extract",
    response_model=OrderExtractionResult,
)
async def extract_order_pdf(
    client_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    """„Zczytaj dane z dokumentu" — odczyt pól z PDF/DOCX zamówienia klienta.

    Świadoma akcja użytkownika, ODDZIELONA od zapisu: NIE tworzy Orderu ani nie
    zapisuje pliku — zwraca tylko odczytane pola do wstawienia w formularzu
    (wszystkie edytowalne). Przy jakiejkolwiek niepewności ``uncertain=True`` →
    front pokazuje baner „Sprawdź dane!". Kwoty zredagowane dla ról bez VIEW_FINANCE.

    Bramkowane: DL przypisany do klienta lub Admin (jak create), plus quota AI
    ``AIFeatureKey.order_parser`` (master → feature → miesięczny limit).
    """
    client = await _assert_client(db, client_id)

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

    # Quota AI — liczone po udanej ekstrakcji, przed wywołaniem Claude, żeby
    # blokada zwróciła 503 bez palenia wywołania modelu (wzorzec cv_match_preview).
    try:
        await check_and_increment(db, AIFeatureKey.order_parser, user_id=user.id)
        await db.commit()
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

    extraction = await parse_order_document(text)
    client_names = " ".join(
        value
        for value in (client.name, client.display_name, client.legal_name)
        if value
    ).casefold()
    if client.name.casefold() == "nordea" or "nordea bank abp" in client_names:
        extraction = enforce_nordea_order_number(extraction, text)

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
        total_value=extraction.total_value if show_finance else None,
        currency=extraction.currency if show_finance else None,
        # Liczba MD jedzie NIEZREDAGOWANA — jest operacyjna, nie finansowa.
        md_total=extraction.md_total,
        uncertain=extraction.uncertain,
        uncertain_reasons=reasons,
        fields_confidence=confidence,
        source=extraction.source,
    )


@router.patch("/{client_id}/orders/{order_id}", response_model=ClientOrderRead)
async def update_order(
    client_id: int,
    order_id: int,
    payload: ClientOrderUpdate,
    user: DlAssignedOrAdmin,
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
        # Harmonogram stawki kandydata dociągany JAWNIE, bo `_apply_candidate_rate`
        # niżej dotyka `contract.candidate_rate_schedule`. Sam `selectinload`
        # na relacji `contract` go nie obejmuje, a sięgnięcie po niego bez
        # wczytania to w sesji async nie wolniejszy odczyt, tylko
        # `MissingGreenlet` — HTTP 500 bez nagłówków CORS, który front pokazuje
        # jako „Network Error".
        .options(
            selectinload(ClientOrder.contract).selectinload(
                Contract.candidate_rate_schedule
            )
        )
        .where(ClientOrder.id == order_id, ClientOrder.client_id == client_id)
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")

    data = payload.model_dump(exclude_unset=True)
    # Stawka KOSZTOWA mieszka na Contract, nie na Order, ale formularz
    # uzupełnienia draftu pokazuje ją obok stawki przychodowej i zapisuje
    # jednym PATCH-em. Przepuszczamy ją TĘDY, zamiast przez PATCH
    # /api/contracts/{id}: tamten handler ma własną, admin-only bramkę
    # osłaniającą 17 pól i ~20 innych odpowiedzi, więc poszerzanie go dla
    # jednego pola rozlałoby dostęp do kwot na całą powierzchnię kontraktów.
    rate_candidate = data.pop("rate_candidate", None)
    if "rate_candidate" in payload.model_fields_set:
        if order.contract is None:
            raise HTTPException(409, detail="Order has no contract to price")
        _apply_candidate_rate(order.contract, rate_candidate, actor_id=user.id)
    if "project_part" in data:
        # Edycja/uzupełnienie draftu: wartość ze słownika albo NULL; u klientów
        # innych niż e-Zdrowie pole pozostaje zabronione (ticket #3).
        try:
            data["project_part"] = validate_project_part(
                client_id, data["project_part"], require=False
            )
        except ValueError as e:
            raise HTTPException(422, detail=str(e)) from None
    for field, value in data.items():
        setattr(order, field, value)

    auto_activated = _activate_complete_draft(order)
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
            },
        )
    )
    await db.commit()
    await db.refresh(order)
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )


@router.delete("/{client_id}/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_order(
    client_id: int,
    order_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft cancel: status=cancelled. Hard delete tylko gdy status=draft."""
    await _assert_client(db, client_id)
    order = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")

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
    await db.commit()


# ── PO file ─────────────────────────────────────────────────────────────────


@router.get("/{client_id}/orders/{order_id}/file")
async def download_order_po(
    client_id: int,
    order_id: int,
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    await _require_client_order_read(db, user, client_id)
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
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """PO PDF-y zamówień danego kontraktu — sekcja „Dokumenty zamówień" w
    zakładce Dokumenty kontraktu. Read-only widok tego samego pliku, pobierany
    istniejącym ``GET /orders/{id}/file`` (nie kopiuje pliku)."""
    contract = await db.scalar(select(Contract).where(Contract.id == contract_id))
    if contract is None:
        raise HTTPException(404, detail="Contract not found")
    await _require_client_order_read(db, user, contract.client_id)

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
    user: TacPlus,
    db: AsyncSession = Depends(get_db),
):
    """PO PDF-y wszystkich zamówień osoby/kontraktora — sekcja „Dokumenty
    zamówień / kontraktów" w Plikach osoby. Ten sam plik co w widoku kontraktu.

    Poufność: PO zawiera stawki, więc filtrujemy po dostępie do klienta —
    pokazujemy tylko zamówienia klientów, których użytkownik może czytać
    (admin/head_of_recruitment = wszystkie, Delivery Lead = przypisane). Spójne
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
            access = await resolve_client_access(db, user, o.client_id)
            can = access.can_view_legal_documents
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
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Flow B — "Nowy kontraktor / zamówienie": atomic Contract + Order create."""
    await _assert_client(db, client_id)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    contract_finance_kwargs, order_finance_kwargs = _flow_b_finance_kwargs(
        payload, user, can_finance=can_finance
    )

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
        status=ClientOrderStatus.draft,
        # PR 6: the activation fact is stamped only by the explicit order
        # status transition, never by an incomplete atomic create.
        filled_at=None,
        start_date=payload.order_start_date,
        end_date=payload.order_end_date,
        created_by_user_id=user.id,
        notes=payload.notes,
        project_part=order_project_part,
        **order_finance_kwargs,
    )
    db.add(order)
    # To samo kryterium co przy późniejszym „Uzupełnij zamówienie": jeżeli
    # formularz atomowy już niesie numer, obie stawki i pełny okres, Order nie
    # powinien zaliczać zbędnego przystanku w zakładce Draft. Kontrakt zachowuje
    # własny, niezależny i bardziej rygorystyczny lifecycle podpisu.
    _activate_complete_draft(order)

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
    await db.commit()

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
    user: DlAssignedOrAdmin,
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
    await db.commit()
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
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Usuń wyłącznie aktualny PDF zamówienia, bez zmiany innych pól."""

    await _assert_client(db, client_id)
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
    await db.commit()
    # Najpierw commit metadanych, potem zwolnienie blobu: awaria dysku nie może
    # cofnąć poprawnego usunięcia z formularza ani zostawić bazy wskazującej na
    # nieistniejący plik.
    storage_service.delete_client_order_po(previous_path)
