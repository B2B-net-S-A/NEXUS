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

from datetime import date, datetime, timezone
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

from app.api.deps import CurrentUser, DlAssignedOrAdmin
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.contract import Contract, ContractStatus, RateUnit
from app.models.job import Job
from app.schemas.client_order import (
    ClientOrderRead,
    ClientOrdersGroupedResponse,
    ClientOrderUpdate,
    ContractWithOrdersRead,
)
from app.schemas.new_contractor_order import (
    NewContractorOrderRequest,
    NewContractorOrderResponse,
)
from app.services import storage_service

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


# ── Helpers ────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    if not await db.scalar(select(Client.id).where(Client.id == client_id)):
        raise HTTPException(404, detail="Client not found")


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


def _normalize_monthly(
    rate: Optional[int],
    rate_unit: Optional[RateUnit],
    billing_hours: Optional[int],
) -> Optional[int]:
    if rate is None:
        return None
    if rate_unit == RateUnit.monthly or rate_unit is None:
        return rate
    if rate_unit == RateUnit.daily:
        return rate * 22
    if rate_unit == RateUnit.hourly:
        return rate * (billing_hours or 160)
    return rate


def _compute_monthly_margin(order: ClientOrder, contract: Contract) -> Optional[int]:
    """Marża/mc dla Order: (Order.rate_client OR Contract.rate_client) - Contract.rate_candidate."""
    rate_client_effective = order.rate_client or contract.rate_client
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


async def _order_to_read(
    db: AsyncSession, order: ClientOrder
) -> ClientOrderRead:
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
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Zwraca listę kontraktorów (per Contract) z historią Orderów per Contract.

    UI: tab "Zamówienia & Kontrakty" pokazuje listę kart (1 karta = 1 kontraktor).
    """
    await _assert_client(db, client_id)

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
                candidate_name=c.candidate.name if c.candidate else "",
                contract_status=c.status.value,
                contract_start_date=c.start_date,
                contract_end_date=c.end_date,
                rate_candidate=c.rate_candidate,
                initial_job_id=c.job_id,
                initial_job_title=c.job.title if c.job else None,
                latest_order_id=latest.id if latest else None,
                latest_order_end_date=latest_end,
                latest_order_rate_client=(
                    (latest.rate_client or c.rate_client) if latest else c.rate_client
                ),
                latest_order_monthly_margin=latest_margin,
                days_to_latest_end=days_to_end,
                orders=orders_read,
            )
        )

    return ClientOrdersGroupedResponse(
        contractors=items, total_contractors=len(items)
    )


# ── Autocomplete for "Dodaj przedłużenie" ──────────────────────────────────


@router.get(
    "/{client_id}/contracts-with-orders",
    response_model=list[ContractWithOrdersRead],
)
async def list_active_contracts_for_extension(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    """Lista aktywnych Contractów + ich latest Order — dla autocomplete w
    "Dodaj przedłużenie".
    """
    # Reuse main list, filter na active/ending tylko
    resp = await list_contractors_with_orders(client_id, _user, db)
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
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
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
    return await _order_to_read(db, order)


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
    rate_client: Optional[int] = Form(None),
    total_value: Optional[str] = Form(None),
    currency: Optional[str] = Form(None),
    framework_contract_id: Optional[int] = Form(None),
    job_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
):
    """Flow A — "Dodaj przedłużenie": tworzy Order pod istniejącym Contract."""
    from decimal import Decimal, InvalidOperation

    await _assert_client(db, client_id)

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

    rel_path: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    filename: Optional[str] = None
    if file is not None:
        filename = file.filename or "po.pdf"
        if not filename.lower().endswith(_ALLOWED_EXT):
            raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")
        content_type = file.content_type
        rel_path, size = storage_service.save_client_order_po(
            order_id=0, upload_filename=filename, source=file.file
        )
        if size > MAX_UPLOAD_BYTES:
            storage_service.delete_client_order_po(rel_path)
            raise HTTPException(413, detail="File too large")

    order = ClientOrder(
        client_id=client_id,
        contract_id=contract_id,
        job_id=job_id,
        framework_contract_id=framework_contract_id,
        title=title,
        description=description,
        status=order_status,
        start_date=start_date,
        end_date=end_date,
        rate_client=rate_client,
        total_value=total_dec,
        currency=currency or contract.currency,
        filename=filename,
        file_path=rel_path,
        content_type=content_type,
        size_bytes=size,
        created_by_user_id=user.id,
        notes=notes,
    )
    db.add(order)
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
    return await _order_to_read(db, order)


@router.patch("/{client_id}/orders/{order_id}", response_model=ClientOrderRead)
async def update_order(
    client_id: int,
    order_id: int,
    payload: ClientOrderUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    order = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(order, field, value)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_updated",
            user_id=user.id,
            details={"order_id": order_id, "changed": list(data.keys())},
        )
    )
    await db.commit()
    await db.refresh(order)
    return await _order_to_read(db, order)


@router.delete(
    "/{client_id}/orders/{order_id}", status_code=status.HTTP_204_NO_CONTENT
)
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
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
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

    # Parse rate_unit
    rate_unit_enum = RateUnit.monthly
    try:
        rate_unit_enum = RateUnit(payload.rate_unit)
    except ValueError:
        raise HTTPException(400, detail="Invalid rate_unit") from None

    contract = Contract(
        candidate_id=payload.candidate_id,
        client_id=client_id,
        job_id=payload.job_id,
        start_date=payload.contract_start_date,
        end_date=payload.contract_end_date,
        rate_client=payload.rate_client,
        rate_candidate=payload.rate_candidate,
        currency=payload.currency,
        rate_unit=rate_unit_enum,
        billing_hours_per_month=payload.billing_hours_per_month,
        status=ContractStatus.active,
        handover_notes=payload.notes,
    )
    db.add(contract)
    await db.flush()  # Get contract.id

    order = ClientOrder(
        client_id=client_id,
        contract_id=contract.id,
        job_id=payload.job_id,
        framework_contract_id=payload.framework_contract_id,
        title=payload.title,
        status=ClientOrderStatus.active,
        start_date=payload.order_start_date,
        end_date=payload.order_end_date,
        rate_client=payload.rate_client,
        total_value=payload.total_value,
        currency=payload.currency,
        created_by_user_id=user.id,
        notes=payload.notes,
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

    # Compute marża (po refresh)
    monthly_margin = _compute_monthly_margin(order, contract) or 0

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
    await _assert_client(db, client_id)
    order = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if order is None:
        raise HTTPException(404, detail="Order not found")

    filename = file.filename or "po.pdf"
    if not filename.lower().endswith(_ALLOWED_EXT):
        raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")
    new_path, size = storage_service.save_client_order_po(
        order_id=order.id, upload_filename=filename, source=file.file
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_client_order_po(new_path)
        raise HTTPException(413, detail="File too large")

    if order.file_path:
        storage_service.delete_client_order_po(order.file_path)
    order.filename = filename
    order.file_path = new_path
    order.content_type = file.content_type
    order.size_bytes = size
    _ = user, datetime, timezone  # touch unused imports (uploaded_by tracked elsewhere)

    await db.commit()
    await db.refresh(order)
    return await _order_to_read(db, order)
