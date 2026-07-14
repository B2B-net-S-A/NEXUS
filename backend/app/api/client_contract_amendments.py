"""Router aneksów: `/api/clients/{client_id}/framework-contracts/{fc_id}/amendments`."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from fastapi import (
    APIRouter,
    BackgroundTasks,
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

from app.api.deps import CurrentUser, FinancialDlAssignedOrAdmin
from app.analytics.scope import require_client_scope
from app.api.financial_access import require_financial_access
from app.services.autenti.client_contracts_sender import ClientDocSendRequest
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_contract_amendment import ClientContractAmendment
from app.models.client_framework_contract import ClientFrameworkContract
from app.schemas.client_contract_amendment import ClientContractAmendmentRead
from app.services import storage_service

router = APIRouter()


MAX_UPLOAD_BYTES = 25 * 1024 * 1024
_ALLOWED_EXT = (".pdf", ".docx", ".doc")


async def _assert_fc(
    db: AsyncSession, client_id: int, fc_id: int
) -> ClientFrameworkContract:
    """Verify client + framework contract existence + relationship."""
    client = await db.scalar(select(Client).where(Client.id == client_id))
    if not client:
        raise HTTPException(404, detail="Client not found")
    fc = await db.scalar(
        select(ClientFrameworkContract).where(
            ClientFrameworkContract.id == fc_id,
            ClientFrameworkContract.client_id == client_id,
        )
    )
    if fc is None:
        raise HTTPException(404, detail="Framework contract not found")
    return fc


def _to_read(a: ClientContractAmendment) -> ClientContractAmendmentRead:
    return ClientContractAmendmentRead(
        id=a.id,
        framework_contract_id=a.framework_contract_id,
        name=a.name,
        effective_date=a.effective_date,
        changes_summary=a.changes_summary,
        old_terms=a.old_terms,
        new_terms=a.new_terms,
        filename=a.filename,
        has_file=a.file_path is not None,
        content_type=a.content_type,
        size_bytes=a.size_bytes,
        uploaded_by=a.uploaded_by,
        uploaded_at=a.uploaded_at,
        created_at=a.created_at,
        updated_at=a.updated_at,
    )


@router.get(
    "/{client_id}/framework-contracts/{fc_id}/amendments",
    response_model=list[ClientContractAmendmentRead],
)
async def list_amendments(
    client_id: int,
    fc_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_financial_access(user)
    await require_client_scope(db, user=user, client_id=client_id, finance=True)
    await _assert_fc(db, client_id, fc_id)
    rows = list(
        (
            await db.execute(
                select(ClientContractAmendment)
                .where(ClientContractAmendment.framework_contract_id == fc_id)
                .order_by(ClientContractAmendment.effective_date.desc())
            )
        ).scalars()
    )
    return [_to_read(a) for a in rows]


@router.post(
    "/{client_id}/framework-contracts/{fc_id}/amendments",
    response_model=ClientContractAmendmentRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_amendment(
    client_id: int,
    fc_id: int,
    user: FinancialDlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    name: str = Form(...),
    effective_date: date = Form(...),
    changes_summary: Optional[str] = Form(None),
    old_terms_json: Optional[str] = Form(None),
    new_terms_json: Optional[str] = Form(None),
):
    import json

    require_financial_access(user)
    await _assert_fc(db, client_id, fc_id)

    def _parse_json(raw: Optional[str], label: str) -> Optional[dict[str, Any]]:
        if raw is None or raw == "":
            return None
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise HTTPException(400, detail=f"Invalid JSON for {label}") from exc
        if not isinstance(data, dict):
            raise HTTPException(400, detail=f"{label} must be a JSON object")
        return data

    old_terms = _parse_json(old_terms_json, "old_terms_json")
    new_terms = _parse_json(new_terms_json, "new_terms_json")

    relative_path: Optional[str] = None
    size: Optional[int] = None
    content_type: Optional[str] = None
    filename: Optional[str] = None
    if file is not None:
        filename = file.filename or "amendment.pdf"
        if not filename.lower().endswith(_ALLOWED_EXT):
            raise HTTPException(415, detail="Tylko pliki PDF/DOCX/DOC")
        content_type = file.content_type
        relative_path, size = storage_service.save_client_contract_amendment(
            framework_contract_id=fc_id,
            upload_filename=filename,
            source=file.file,
        )
        if size > MAX_UPLOAD_BYTES:
            storage_service.delete_client_contract_amendment(relative_path)
            raise HTTPException(413, detail="File too large")

    a = ClientContractAmendment(
        framework_contract_id=fc_id,
        name=name,
        effective_date=effective_date,
        changes_summary=changes_summary,
        old_terms=old_terms,
        new_terms=new_terms,
        filename=filename,
        file_path=relative_path,
        content_type=content_type,
        size_bytes=size,
        uploaded_by=user.id if file is not None else None,
        uploaded_at=datetime.now(timezone.utc) if file is not None else None,
    )
    db.add(a)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_amendment_added",
            user_id=user.id,
            details={
                "fc_id": fc_id,
                "name": name,
                "effective_date": str(effective_date),
            },
        )
    )
    await db.flush()
    await db.refresh(a)
    await db.commit()
    return _to_read(a)


@router.get(
    "/{client_id}/framework-contracts/{fc_id}/amendments/{amendment_id}/file",
)
async def download_amendment(
    client_id: int,
    fc_id: int,
    amendment_id: int,
    user: CurrentUser,
    db: AsyncSession = Depends(get_db),
):
    require_financial_access(user)
    await require_client_scope(db, user=user, client_id=client_id, finance=True)
    await _assert_fc(db, client_id, fc_id)
    a = await db.scalar(
        select(ClientContractAmendment).where(
            ClientContractAmendment.id == amendment_id,
            ClientContractAmendment.framework_contract_id == fc_id,
        )
    )
    if a is None or a.file_path is None:
        raise HTTPException(404, detail="File not found")
    abs_path = storage_service.get_client_contract_amendment_path(a.file_path)
    return FileResponse(
        path=str(abs_path),
        filename=a.filename or "amendment.pdf",
        media_type=a.content_type or "application/pdf",
    )


@router.post(
    "/{client_id}/framework-contracts/{fc_id}/amendments/{amendment_id}/send-autenti",
    status_code=status.HTTP_202_ACCEPTED,
)
async def send_amendment_to_autenti(
    client_id: int,
    fc_id: int,
    amendment_id: int,
    payload: ClientDocSendRequest,
    user: FinancialDlAssignedOrAdmin,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    require_financial_access(user)
    from app.services.autenti.client_contracts_sender import (
        prepare_send_amendment,
        send_pdf_to_autenti,
    )

    await _assert_fc(db, client_id, fc_id)
    a = await db.scalar(
        select(ClientContractAmendment).where(
            ClientContractAmendment.id == amendment_id,
            ClientContractAmendment.framework_contract_id == fc_id,
        )
    )
    if a is None:
        raise HTTPException(404, detail="Amendment not found")
    sig = await prepare_send_amendment(
        db, amendment_id=amendment_id, payload=payload, sender_user=user
    )
    background_tasks.add_task(send_pdf_to_autenti, sig.id)
    return {"signature_id": sig.id, "status": sig.status.value}


@router.delete(
    "/{client_id}/framework-contracts/{fc_id}/amendments/{amendment_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_amendment(
    client_id: int,
    fc_id: int,
    amendment_id: int,
    user: FinancialDlAssignedOrAdmin,
    db: AsyncSession = Depends(get_db),
):
    require_financial_access(user)
    await _assert_fc(db, client_id, fc_id)
    a = await db.scalar(
        select(ClientContractAmendment).where(
            ClientContractAmendment.id == amendment_id,
            ClientContractAmendment.framework_contract_id == fc_id,
        )
    )
    if a is None:
        raise HTTPException(404, detail="Amendment not found")

    if a.file_path:
        storage_service.delete_client_contract_amendment(a.file_path)
    await db.delete(a)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="framework_contract_amendment_deleted",
            user_id=user.id,
            details={"fc_id": fc_id, "amendment_id": amendment_id},
        )
    )
    await db.commit()
