"""Router `/api/clients/{client_id}/orders` — Statement of Work / Zamówienia.

Order grupuje kandydackie Contract'y (M:N przez ``client_order_contracts``).
Marża per order liczy się dynamicznie z ``Contract.rate_client - rate_candidate``
przeliczonego na miesięczną stawkę (``monthly_rate`` helper na modelu).
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import CurrentUser, DlAssignedOrAdmin
from app.core.database import get_db
from app.models.activity import Activity
from app.models.candidate import Candidate
from app.models.client import Client
from app.models.client_framework_contract import ClientFrameworkContract
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_contract import ClientOrderContract
from app.models.contract import Contract, ContractStatus
from app.schemas.client_order import (
    ClientOrderListResponse,
    ClientOrderRead,
    ClientOrderUpdate,
    ClientOrderWithContractsRead,
    OrderContractLink,
    OrderContractLinkRead,
)
from app.services import storage_service

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    if not await db.scalar(select(Client.id).where(Client.id == client_id)):
        raise HTTPException(404, detail="Client not found")


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


async def _compute_order_aggregates(
    db: AsyncSession, order_id: int
) -> dict:
    """Zwraca {linked_count, filled_positions, monthly_margin_total}.

    `filled_positions` = count linkowanych kontraktów z status active.
    `monthly_margin_total` = suma `monthly_margin` (rate_client - rate_candidate
    znormalizowane do miesięcznej stawki) z linkowanych aktywnych kontraktów.
    """
    rows = list(
        (
            await db.execute(
                select(Contract)
                .join(
                    ClientOrderContract,
                    ClientOrderContract.contract_id == Contract.id,
                )
                .where(ClientOrderContract.order_id == order_id)
            )
        ).scalars()
    )
    linked = len(rows)
    filled = sum(1 for c in rows if c.status == ContractStatus.active)
    total_margin = 0
    has_any = False
    for c in rows:
        if c.status != ContractStatus.active:
            continue
        m = c.monthly_margin
        if m is not None:
            total_margin += m
            has_any = True
    return {
        "linked_count": linked,
        "filled_positions": filled,
        "monthly_margin_total": total_margin if has_any else None,
    }


async def _to_read(
    db: AsyncSession, o: ClientOrder
) -> ClientOrderRead:
    agg = await _compute_order_aggregates(db, o.id)
    margin_pct: Optional[float] = None
    if (
        agg["monthly_margin_total"] is not None
        and o.total_value
        and float(o.total_value) > 0
    ):
        # Bardzo zgrubny pct — % marży miesięcznej w stosunku do całkowitej wartości
        # zamówienia. Lepsza metryka pojawi się jak będzie known monthly billing.
        margin_pct = round(
            float(agg["monthly_margin_total"]) / float(o.total_value) * 100, 2
        )

    return ClientOrderRead(
        id=o.id,
        client_id=o.client_id,
        framework_contract_id=o.framework_contract_id,
        title=o.title,
        description=o.description,
        status=o.status,
        start_date=o.start_date,
        end_date=o.end_date,
        total_value=o.total_value,
        currency=o.currency,
        positions_count=o.positions_count,
        filename=o.filename,
        has_file=o.file_path is not None,
        content_type=o.content_type,
        size_bytes=o.size_bytes,
        created_by_user_id=o.created_by_user_id,
        notes=o.notes,
        created_at=o.created_at,
        updated_at=o.updated_at,
        linked_contracts_count=agg["linked_count"],
        filled_positions=agg["filled_positions"],
        monthly_margin_total=agg["monthly_margin_total"],
        monthly_margin_pct=margin_pct,
        days_to_end=_days_to(o.end_date),
    )


# ── List + read ─────────────────────────────────────────────────────────────


@router.get(
    "/{client_id}/orders",
    response_model=ClientOrderListResponse,
)
async def list_orders(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[ClientOrderStatus] = None,
):
    await _assert_client(db, client_id)
    stmt = select(ClientOrder).where(ClientOrder.client_id == client_id)
    if status_filter is not None:
        stmt = stmt.where(ClientOrder.status == status_filter)
    stmt = stmt.order_by(ClientOrder.start_date.desc().nullslast())
    rows = list((await db.execute(stmt)).scalars())
    items = [await _to_read(db, o) for o in rows]
    return ClientOrderListResponse(items=items, total=len(items))


@router.get(
    "/{client_id}/orders/{order_id}",
    response_model=ClientOrderWithContractsRead,
)
async def get_order(
    client_id: int,
    order_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    o = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id,
            ClientOrder.client_id == client_id,
        )
    )
    if o is None:
        raise HTTPException(404, detail="Order not found")

    base = await _to_read(db, o)
    rows = list(
        (
            await db.execute(
                select(ClientOrderContract)
                .options(
                    selectinload(ClientOrderContract.contract).selectinload(
                        Contract.candidate
                    )
                )
                .where(ClientOrderContract.order_id == order_id)
                .order_by(ClientOrderContract.assigned_at.desc())
            )
        ).scalars()
    )
    contracts: list[OrderContractLinkRead] = []
    for link in rows:
        c: Contract = link.contract
        cand: Optional[Candidate] = c.candidate if c else None
        contracts.append(
            OrderContractLinkRead(
                id=link.id,
                contract_id=c.id if c else 0,
                candidate_id=cand.id if cand else None,
                candidate_name=cand.name if cand else None,
                rate_client=c.rate_client if c else None,
                rate_candidate=c.rate_candidate if c else None,
                monthly_margin=c.monthly_margin if c else None,
                contract_status=c.status.value if c and c.status else None,
                contract_start_date=c.start_date if c else None,
                contract_end_date=c.end_date if c else None,
                assigned_at=link.assigned_at,
            )
        )

    return ClientOrderWithContractsRead(**base.model_dump(), contracts=contracts)


# ── Create + update + delete ────────────────────────────────────────────────


@router.post(
    "/{client_id}/orders",
    response_model=ClientOrderRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    client_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    framework_contract_id: int = Form(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    order_status: ClientOrderStatus = Form(ClientOrderStatus.draft),
    start_date: Optional[date] = Form(None),
    end_date: Optional[date] = Form(None),
    total_value: Optional[str] = Form(None),
    currency: Optional[str] = Form(None),
    positions_count: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
):
    from decimal import Decimal, InvalidOperation

    await _assert_client(db, client_id)

    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == framework_contract_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(
            400, detail="framework_contract_id must reference an MSA of this client"
        )

    total_dec: Optional[Decimal] = None
    if total_value:
        try:
            total_dec = Decimal(total_value)
        except (InvalidOperation, ValueError) as exc:
            raise HTTPException(400, detail="Invalid total_value") from exc

    relative_path: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    filename: Optional[str] = None
    if file is not None:
        filename = file.filename or "po.pdf"
        if not filename.lower().endswith(_ALLOWED_EXT):
            raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")
        content_type = file.content_type
        # Order id known dopiero po flush — zapisujemy do tymczasowego "0"
        # i przeniesiemy po insercie.
        relative_path, size = storage_service.save_client_order_po(
            order_id=0, upload_filename=filename, source=file.file
        )
        if size > MAX_UPLOAD_BYTES:
            storage_service.delete_client_order_po(relative_path)
            raise HTTPException(413, detail="File too large")

    o = ClientOrder(
        client_id=client_id,
        framework_contract_id=framework_contract_id,
        title=title,
        description=description,
        status=order_status,
        start_date=start_date,
        end_date=end_date,
        total_value=total_dec,
        currency=currency or fc.currency,
        positions_count=positions_count,
        filename=filename,
        file_path=relative_path,
        content_type=content_type,
        size_bytes=size,
        created_by_user_id=user.id,
        notes=notes,
    )
    db.add(o)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_created",
            user_id=user.id,
            details={
                "title": title,
                "framework_contract_id": framework_contract_id,
                "status": order_status.value,
            },
        )
    )
    await db.flush()
    await db.refresh(o)
    await db.commit()
    return await _to_read(db, o)


@router.patch(
    "/{client_id}/orders/{order_id}",
    response_model=ClientOrderRead,
)
async def update_order(
    client_id: int,
    order_id: int,
    payload: ClientOrderUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    o = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if o is None:
        raise HTTPException(404, detail="Order not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(o, field, value)

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
    await db.refresh(o)
    return await _to_read(db, o)


@router.delete(
    "/{client_id}/orders/{order_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_order(
    client_id: int,
    order_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft-cancel: status=cancelled. Hard delete tylko gdy status=draft i 0 contractów."""
    await _assert_client(db, client_id)
    o = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if o is None:
        raise HTTPException(404, detail="Order not found")

    linked = await db.scalar(
        select(func.count())
        .select_from(ClientOrderContract)
        .where(ClientOrderContract.order_id == order_id)
    )

    if o.status == ClientOrderStatus.draft and linked == 0:
        if o.file_path:
            storage_service.delete_client_order_po(o.file_path)
        await db.delete(o)
    else:
        o.status = ClientOrderStatus.cancelled

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_cancelled",
            user_id=user.id,
            details={"order_id": order_id, "hard": linked == 0 and o.status == ClientOrderStatus.draft},
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
    o = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if o is None or o.file_path is None:
        raise HTTPException(404, detail="File not found")
    abs_path = storage_service.get_client_order_po_path(o.file_path)
    return FileResponse(
        path=str(abs_path),
        filename=o.filename or "po.pdf",
        media_type=o.content_type or "application/pdf",
    )


# ── Link / unlink candidate Contract ────────────────────────────────────────


@router.post(
    "/{client_id}/orders/{order_id}/contracts",
    response_model=OrderContractLinkRead,
    status_code=status.HTTP_201_CREATED,
)
async def link_contract(
    client_id: int,
    order_id: int,
    payload: OrderContractLink,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    o = await db.scalar(
        select(ClientOrder).where(
            ClientOrder.id == order_id, ClientOrder.client_id == client_id
        )
    )
    if o is None:
        raise HTTPException(404, detail="Order not found")

    contract = await db.scalar(
        select(Contract).where(Contract.id == payload.contract_id)
    )
    if contract is None:
        raise HTTPException(404, detail="Candidate contract not found")
    if contract.client_id != client_id:
        raise HTTPException(
            400, detail="Contract belongs to a different client"
        )

    existing = await db.scalar(
        select(ClientOrderContract).where(
            ClientOrderContract.order_id == order_id,
            ClientOrderContract.contract_id == payload.contract_id,
        )
    )
    if existing is not None:
        raise HTTPException(409, detail="Contract already linked")

    link = ClientOrderContract(
        order_id=order_id,
        contract_id=payload.contract_id,
        assigned_by_user_id=user.id,
    )
    db.add(link)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_contract_linked",
            user_id=user.id,
            details={"order_id": order_id, "contract_id": payload.contract_id},
        )
    )
    await db.flush()
    await db.refresh(link)
    await db.commit()

    cand = await db.scalar(select(Candidate).where(Candidate.id == contract.candidate_id))
    return OrderContractLinkRead(
        id=link.id,
        contract_id=contract.id,
        candidate_id=cand.id if cand else None,
        candidate_name=cand.name if cand else None,
        rate_client=contract.rate_client,
        rate_candidate=contract.rate_candidate,
        monthly_margin=contract.monthly_margin,
        contract_status=contract.status.value,
        contract_start_date=contract.start_date,
        contract_end_date=contract.end_date,
        assigned_at=link.assigned_at,
    )


@router.delete(
    "/{client_id}/orders/{order_id}/contracts/{contract_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def unlink_contract(
    client_id: int,
    order_id: int,
    contract_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    link = await db.scalar(
        select(ClientOrderContract).where(
            ClientOrderContract.order_id == order_id,
            ClientOrderContract.contract_id == contract_id,
        )
    )
    if link is None:
        raise HTTPException(404, detail="Link not found")
    await db.delete(link)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="order_contract_unlinked",
            user_id=user.id,
            details={"order_id": order_id, "contract_id": contract_id},
        )
    )
    await db.commit()
