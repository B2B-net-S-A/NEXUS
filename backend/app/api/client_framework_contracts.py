"""Router `/api/clients/{client_id}/framework-contracts` — MSA per klient.

Reads (GET) — `CurrentUser` (każdy zalogowany).
Writes (POST/PATCH/DELETE) — `DlAssignedOrAdmin` (admin/HoR globalnie albo
DL przypisany do klienta).

Pattern multipart upload — zaczerpnięte z `client_materials.py` (one-pagers).
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import (
    CurrentUser,
    DlAssignedOrAdmin,
)
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import (
    ClientFrameworkContract,
    FrameworkContractSignedVia,
    FrameworkContractStatus,
)
from app.schemas.client_framework_contract import (
    ClientFrameworkContractListResponse,
    ClientFrameworkContractRead,
    ClientFrameworkContractUpdate,
)
from app.services import storage_service

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024  # 25 MB — MSA bywa duży

_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/octet-stream",
}
_ALLOWED_EXT_RE = (".pdf", ".docx", ".doc")


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")


def _validate_upload(file: UploadFile) -> None:
    filename = file.filename or "file"
    mime = (file.content_type or "").lower()
    ext_ok = filename.lower().endswith(_ALLOWED_EXT_RE)
    if mime not in _ALLOWED_MIME and not ext_ok:
        raise HTTPException(
            status_code=415, detail="Tylko pliki PDF/DOCX/DOC"
        )
    if not ext_ok:
        raise HTTPException(
            status_code=415,
            detail="Nazwa pliku musi mieć rozszerzenie .pdf/.docx/.doc",
        )


def _days_to(target: Optional[date]) -> Optional[int]:
    if target is None:
        return None
    return (target - date.today()).days


async def _to_read(
    db: AsyncSession, fc: ClientFrameworkContract
) -> ClientFrameworkContractRead:
    amendments_count = await db.scalar(
        select(func.count())
        .select_from(ClientContractAmendment)
        .where(ClientContractAmendment.framework_contract_id == fc.id)
    )
    return ClientFrameworkContractRead(
        id=fc.id,
        client_id=fc.client_id,
        name=fc.name,
        status=fc.status,
        effective_date=fc.effective_date,
        expiry_date=fc.expiry_date,
        signed_via=fc.signed_via,
        currency=fc.currency,
        parent_contract_id=fc.parent_contract_id,
        contract_terms_id=fc.contract_terms_id,
        filename=fc.filename,
        has_file=fc.file_path is not None,
        content_type=fc.content_type,
        size_bytes=fc.size_bytes,
        uploaded_by=fc.uploaded_by,
        uploaded_at=fc.uploaded_at,
        notes=fc.notes,
        created_at=fc.created_at,
        updated_at=fc.updated_at,
        amendments_count=amendments_count or 0,
        days_to_expiry=_days_to(fc.expiry_date),
    )


# ── List + read ─────────────────────────────────────────────────────────────


@router.get(
    "/{client_id}/framework-contracts",
    response_model=ClientFrameworkContractListResponse,
)
async def list_framework_contracts(
    client_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
    status_filter: Optional[FrameworkContractStatus] = None,
):
    await _assert_client(db, client_id)
    stmt = select(ClientFrameworkContract).where(
        ClientFrameworkContract.client_id == client_id
    )
    if status_filter is not None:
        stmt = stmt.where(ClientFrameworkContract.status == status_filter)
    stmt = stmt.order_by(ClientFrameworkContract.effective_date.desc().nullslast())
    rows = list((await db.execute(stmt)).scalars().all())
    items = [await _to_read(db, fc) for fc in rows]
    return ClientFrameworkContractListResponse(items=items, total=len(items))


@router.get(
    "/{client_id}/framework-contracts/{fc_id}",
    response_model=ClientFrameworkContractRead,
)
async def get_framework_contract(
    client_id: int,
    fc_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")
    return await _to_read(db, fc)


# ── Create + update + delete ────────────────────────────────────────────────


@router.post(
    "/{client_id}/framework-contracts",
    response_model=ClientFrameworkContractRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_framework_contract(
    client_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    name: str = Form(...),
    contract_status: FrameworkContractStatus = Form(FrameworkContractStatus.draft),
    effective_date: Optional[date] = Form(None),
    expiry_date: Optional[date] = Form(None),
    signed_via: FrameworkContractSignedVia = Form(FrameworkContractSignedVia.upload),
    currency: Optional[str] = Form(None),
    parent_contract_id: Optional[int] = Form(None),
    contract_terms_id: Optional[int] = Form(None),
    notes: Optional[str] = Form(None),
):
    await _assert_client(db, client_id)

    relative_path = None
    size = None
    content_type = None
    filename = None
    if file is not None:
        _validate_upload(file)
        filename = file.filename
        content_type = file.content_type
        relative_path, size = storage_service.save_client_framework_contract(
            client_id=client_id,
            upload_filename=filename or "msa.pdf",
            source=file.file,
        )
        if size > MAX_UPLOAD_BYTES:
            storage_service.delete_client_framework_contract(relative_path)
            raise HTTPException(
                status_code=413,
                detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
            )

    fc = ClientFrameworkContract(
        client_id=client_id,
        name=name,
        status=contract_status,
        effective_date=effective_date,
        expiry_date=expiry_date,
        signed_via=signed_via,
        currency=currency,
        parent_contract_id=parent_contract_id,
        contract_terms_id=contract_terms_id,
        filename=filename,
        file_path=relative_path,
        content_type=content_type,
        size_bytes=size,
        uploaded_by=user.id if file is not None else None,
        uploaded_at=datetime.now(timezone.utc) if file is not None else None,
        notes=notes,
    )
    db.add(fc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_created",
            user_id=user.id,
            details={"name": name, "status": contract_status.value},
        )
    )
    await db.flush()
    await db.refresh(fc)
    await db.commit()
    return await _to_read(db, fc)


@router.patch(
    "/{client_id}/framework-contracts/{fc_id}",
    response_model=ClientFrameworkContractRead,
)
async def update_framework_contract(
    client_id: int,
    fc_id: int,
    payload: ClientFrameworkContractUpdate,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    data = payload.model_dump(exclude_unset=True)
    for field, value in data.items():
        setattr(fc, field, value)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_updated",
            user_id=user.id,
            details={"fc_id": fc_id, "changed": list(data.keys())},
        )
    )
    await db.commit()
    await db.refresh(fc)
    return await _to_read(db, fc)


@router.delete(
    "/{client_id}/framework-contracts/{fc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_framework_contract(
    client_id: int,
    fc_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    """Soft-delete: status → `superseded`. Hard delete tylko gdy `draft`."""
    await _assert_client(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    if fc.status == FrameworkContractStatus.draft:
        if fc.file_path:
            storage_service.delete_client_framework_contract(fc.file_path)
        await db.delete(fc)
    else:
        fc.status = FrameworkContractStatus.superseded

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_deleted",
            user_id=user.id,
            details={"fc_id": fc_id, "hard_delete": fc.status.value == "draft"},
        )
    )
    await db.commit()


# ── File upload (replace) + download ────────────────────────────────────────


@router.put(
    "/{client_id}/framework-contracts/{fc_id}/file",
    response_model=ClientFrameworkContractRead,
)
async def replace_framework_contract_file(
    client_id: int,
    fc_id: int,
    user: DlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    await _assert_client(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")

    _validate_upload(file)
    new_path, size = storage_service.save_client_framework_contract(
        client_id=client_id,
        upload_filename=file.filename or "msa.pdf",
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_client_framework_contract(new_path)
        raise HTTPException(413, detail="File too large")

    if fc.file_path:
        storage_service.delete_client_framework_contract(fc.file_path)

    fc.filename = file.filename
    fc.file_path = new_path
    fc.content_type = file.content_type
    fc.size_bytes = size
    fc.uploaded_by = user.id
    fc.uploaded_at = datetime.now(timezone.utc)

    await db.commit()
    await db.refresh(fc)
    return await _to_read(db, fc)


@router.get("/{client_id}/framework-contracts/{fc_id}/file")
async def download_framework_contract(
    client_id: int,
    fc_id: int,
    _user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    await _assert_client(db, client_id)
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None or fc.file_path is None:
        raise HTTPException(404, detail="File not found")
    abs_path = storage_service.get_client_framework_contract_path(fc.file_path)
    return FileResponse(
        path=str(abs_path),
        filename=fc.filename or "msa.pdf",
        media_type=fc.content_type or "application/pdf",
    )
