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
from app.models.activity import Activity
from app.models.ai_feature import AIFeatureKey
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job
from app.models.user import UserRole
from app.schemas.client_order import (
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
from app.services.ezdrowie import validate_project_part
from app.services.cv_text_extractor import UnsupportedCvFormat, extract_text
from app.services.order_pdf_parser import parse_order_document

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


# ── Helpers ────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    if not await db.scalar(select(Client.id).where(Client.id == client_id)):
        raise HTTPException(404, detail="Client not found")


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
) -> None:
    """Zapisz PO na dysku i przypnij metadane do Orderu (bez commitu).

    Kasuje poprzedni plik, jeśli był — zamówienie ma dokładnie jeden PO, więc
    stary blob po podmianie nie ma już żadnego czytelnika i zostałby sierotą
    na wolumenie.
    """

    import io

    previous = order.file_path
    rel_path, size = storage_service.save_client_order_po(
        order_id=order.id, upload_filename=filename, source=io.BytesIO(payload)
    )
    if previous:
        storage_service.delete_client_order_po(previous)
    order.filename = filename
    order.file_path = rel_path
    order.content_type = content_type
    order.size_bytes = size
    order.file_uploaded_by = user.id
    order.file_uploaded_at = datetime.now(timezone.utc)


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
    order: ClientOrder, contract: Contract
) -> Optional[Decimal | int]:
    """Marża/mc dla Order: (Order.rate_client ?? Contract.rate_client) - Contract.rate_candidate."""
    # `is not None` zamiast `or` — stawka 0 na Orderze jest legalna i nie może
    # po cichu spadać do stawki kontraktu.
    rate_client_effective = (
        order.rate_client if order.rate_client is not None else contract.rate_client
    )
    if rate_client_effective is None or contract.rate_candidate is None:
        return None
    monthly_client = _normalize_monthly(
        rate_client_effective, contract.rate_unit, contract.billing_hours_per_month
    )
    monthly_cand = _normalize_monthly(
        contract.rate_candidate, contract.rate_unit, contract.billing_hours_per_month
    )
    if monthly_client is None or monthly_cand is None:
        return None
    return monthly_client - monthly_cand


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


async def _order_to_read(db: AsyncSession, order: ClientOrder) -> ClientOrderRead:
    """Pełny widok Orderu z computed fields (candidate_name, monthly_margin, etc)."""
    contract = order.contract or await db.scalar(
        select(Contract).where(Contract.id == order.contract_id)
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
                    selectinload(Contract.candidate),
                    selectinload(Contract.client_orders),
                    selectinload(Contract.job),
                )
                .where(Contract.client_id == client_id)
                .order_by(Contract.start_date.desc().nullslast())
            )
        ).scalars()
    )

    items: list[ContractWithOrdersRead] = []
    today = date.today()
    for c in contracts:
        orders_list = sorted(
            c.client_orders or [],
            key=lambda o: o.start_date or date.min,
            reverse=True,
        )
        latest = orders_list[0] if orders_list else None

        latest_margin = _compute_monthly_margin(latest, c) if latest else None
        latest_end = latest.end_date if latest else None
        days_to_end = (latest_end - today).days if latest_end else None

        orders_read = [await _order_to_read(db, o) for o in orders_list]

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
                rate_candidate=c.rate_candidate,
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
                        else c.rate_client
                    )
                    if latest
                    else c.rate_client
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
                "status": order_status.value,
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
    await _assert_client(db, client_id)

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
        .options(selectinload(ClientOrder.contract))
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
        order.contract.rate_candidate = rate_candidate
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
    monthly_margin = _compute_monthly_margin(order, contract) if can_finance else None

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
    _attach_po_bytes(
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
    await db.refresh(order)
    can_finance = _can_manage_order_finance(
        user, dl_assigned=await _dl_assigned_to_client(db, user, client_id)
    )
    return _order_response_for_user(
        await _order_to_read(db, order), user, can_finance=can_finance
    )
