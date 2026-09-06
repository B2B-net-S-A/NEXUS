"""Client "Materiały" sub-tab: one-pagers (file uploads) + contract terms.

Routes are declared without a prefix so the router can be registered with
`prefix="/api"` in main.py — mirrors the client_knowledge pattern.

One-pagers
  GET    /clients/{client_id}/one-pagers           (ClientAccess.can_view_materials)
  POST   /clients/{client_id}/one-pagers           (can_edit_materials)
  GET    /clients/{client_id}/one-pagers/{id}/download (can_view_materials)
  DELETE /clients/{client_id}/one-pagers/{id}      (can_edit_materials)

Contract terms (singleton per client, upsert)
  GET    /clients/{client_id}/contract-terms       (can_view_legal_documents)
  PUT    /clients/{client_id}/contract-terms       (can_edit_legal_documents)

Aktualnie całość podlega bramce Delivery. TCM może czytać one-pagery, ale nie
warunki prawne; Admin i przypisany DL mogą zapisywać, a Finance ma odczyt.
"""

from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user
from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_contract_terms import ClientContractTerms
from app.models.client_one_pager import ClientOnePager
from app.models.user import User
from app.schemas.client_materials import (
    ClientContractTermsResponse,
    ClientContractTermsUpsert,
    ClientOnePagerResponse,
)
from app.services import storage_service
from app.services.client_access import (
    deny,
    resolve_client_access,
)


router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB

_ALLOWED_MIME = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
    "application/octet-stream",  # some browsers mislabel — fallback to extension check
}

_ALLOWED_EXT_RE = (".pdf", ".docx", ".doc")


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")


async def _require_material_write(
    db: AsyncSession,
    current_user: User,
    client_id: int,
    *,
    legal: bool = False,
) -> None:
    access = await resolve_client_access(db, current_user, client_id)
    allowed = access.can_edit_legal_documents if legal else access.can_edit_materials
    if not allowed:
        if legal:
            raise deny(
                "zapis dokumentów prawnych wymaga roli admin lub przypisanego DL"
            )
        raise deny("zapis materiałów wymaga roli admin lub Delivery Lead")


async def require_client_material_read_access(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_materials:
        raise deny("brak dostępu do materiałów tego klienta")
    return current_user


async def require_client_material_write_access(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    await _require_material_write(db, current_user, client_id)
    return current_user


async def require_client_legal_read_access(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    access = await resolve_client_access(db, current_user, client_id)
    if not access.can_view_legal_documents:
        raise deny("warunki umów wymagają jawnego przypisania klienta")
    return current_user


async def require_client_legal_write_access(
    client_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    await _require_material_write(db, current_user, client_id, legal=True)
    return current_user


ClientMaterialReadUser = Annotated[
    User,
    Depends(require_client_material_read_access),
]
ClientMaterialWriteUser = Annotated[
    User,
    Depends(require_client_material_write_access),
]
ClientLegalReadUser = Annotated[
    User,
    Depends(require_client_legal_read_access),
]
ClientLegalWriteUser = Annotated[
    User,
    Depends(require_client_legal_write_access),
]


async def _resolve_user_email(
    db: AsyncSession, user_id: Optional[int]
) -> Optional[str]:
    if not user_id:
        return None
    return await db.scalar(select(User.email).where(User.id == user_id))


async def _one_pager_to_response(
    db: AsyncSession, op: ClientOnePager
) -> ClientOnePagerResponse:
    email = await _resolve_user_email(db, op.uploaded_by)
    return ClientOnePagerResponse(
        id=op.id,
        client_id=op.client_id,
        title=op.title,
        description=op.description,
        version=op.version,
        filename=op.filename,
        content_type=op.content_type,
        size_bytes=op.size_bytes,
        uploaded_by=op.uploaded_by,
        uploaded_by_email=email,
        created_at=op.created_at,
    )


async def _terms_to_response(
    db: AsyncSession, terms: ClientContractTerms
) -> ClientContractTermsResponse:
    email = await _resolve_user_email(db, terms.updated_by)
    return ClientContractTermsResponse(
        id=terms.id,
        client_id=terms.client_id,
        off_limits_months=terms.off_limits_months,
        off_limits_scope=terms.off_limits_scope,
        off_limits_notes=terms.off_limits_notes,
        internalization_fee_pct=terms.internalization_fee_pct,
        internalization_min_months=terms.internalization_min_months,
        internalization_notice_days=terms.internalization_notice_days,
        internalization_notes=terms.internalization_notes,
        payment_net_days=terms.payment_net_days,
        payment_currency=terms.payment_currency,
        payment_invoice_cycle=terms.payment_invoice_cycle,
        payment_late_fees=terms.payment_late_fees,
        payment_notes=terms.payment_notes,
        notice_period_days=terms.notice_period_days,
        warranty_replacement_days=terms.warranty_replacement_days,
        warranty_notes=terms.warranty_notes,
        other_clauses=terms.other_clauses,
        updated_by=terms.updated_by,
        updated_by_email=email,
        created_at=terms.created_at,
        updated_at=terms.updated_at,
    )


# ── One-pagers ───────────────────────────────────────────────────────────────


@router.get(
    "/clients/{client_id}/one-pagers",
    response_model=List[ClientOnePagerResponse],
)
async def list_one_pagers(
    client_id: int,
    current_user: ClientMaterialReadUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientOnePager)
        .where(ClientOnePager.client_id == client_id)
        .order_by(ClientOnePager.created_at.desc())
    )
    pagers = list(result.scalars().all())
    return [await _one_pager_to_response(db, p) for p in pagers]


@router.post(
    "/clients/{client_id}/one-pagers",
    response_model=ClientOnePagerResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_one_pager(
    client_id: int,
    current_user: ClientMaterialWriteUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
    title: str = Form(...),
    description: Optional[str] = Form(None),
    version: Optional[str] = Form(None),
):
    # MIME + extension allowlist (extension is the fallback — browsers mislabel)
    filename = file.filename or "file"
    mime = (file.content_type or "").lower()
    ext_ok = filename.lower().endswith(_ALLOWED_EXT_RE)
    if mime not in _ALLOWED_MIME and not ext_ok:
        raise HTTPException(
            status_code=415,
            detail="Tylko pliki PDF/DOCX/DOC",
        )
    if not ext_ok:
        raise HTTPException(
            status_code=415,
            detail="Nazwa pliku musi mieć rozszerzenie .pdf/.docx/.doc",
        )

    relative_path, size = storage_service.save_client_one_pager(
        client_id=client_id,
        upload_filename=filename,
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_client_one_pager(relative_path)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    op = ClientOnePager(
        client_id=client_id,
        title=title,
        description=description,
        version=version,
        filename=filename,
        file_path=relative_path,
        content_type=file.content_type,
        size_bytes=size,
        uploaded_by=current_user.id,
    )
    db.add(op)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="one_pager_uploaded",
            user_id=current_user.id,
            details={
                "title": title,
                "filename": filename,
                "size_bytes": size,
            },
        )
    )
    await db.flush()
    await db.refresh(op)
    return await _one_pager_to_response(db, op)


@router.get(
    "/clients/{client_id}/one-pagers/{one_pager_id}/download",
)
async def download_one_pager(
    client_id: int,
    one_pager_id: int,
    current_user: ClientMaterialReadUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientOnePager).where(
            ClientOnePager.id == one_pager_id,
            ClientOnePager.client_id == client_id,
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="One-pager not found")

    try:
        abs_path = storage_service.get_client_one_pager_path(op.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File missing on disk") from exc

    return FileResponse(
        path=str(abs_path),
        filename=op.filename,
        media_type=op.content_type or "application/octet-stream",
    )


@router.delete(
    "/clients/{client_id}/one-pagers/{one_pager_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_one_pager(
    client_id: int,
    one_pager_id: int,
    current_user: ClientMaterialWriteUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientOnePager).where(
            ClientOnePager.id == one_pager_id,
            ClientOnePager.client_id == client_id,
        )
    )
    op = result.scalar_one_or_none()
    if not op:
        raise HTTPException(status_code=404, detail="One-pager not found")

    storage_service.delete_client_one_pager(op.file_path)
    await db.delete(op)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="one_pager_deleted",
            user_id=current_user.id,
            details={"title": op.title, "filename": op.filename},
        )
    )
    await db.flush()
    return None


# ── Contract terms (singleton per client) ────────────────────────────────────


@router.get(
    "/clients/{client_id}/contract-terms",
    response_model=ClientContractTermsResponse | None,
)
async def get_contract_terms(
    client_id: int,
    current_user: ClientLegalReadUser,
    db: AsyncSession = Depends(get_db),
) -> ClientContractTermsResponse | None:
    result = await db.execute(
        select(ClientContractTerms).where(ClientContractTerms.client_id == client_id)
    )
    terms = result.scalar_one_or_none()
    if not terms:
        return None
    return await _terms_to_response(db, terms)


@router.put(
    "/clients/{client_id}/contract-terms",
    response_model=ClientContractTermsResponse,
)
async def upsert_contract_terms(
    client_id: int,
    data: ClientContractTermsUpsert,
    current_user: ClientLegalWriteUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientContractTerms).where(ClientContractTerms.client_id == client_id)
    )
    terms = result.scalar_one_or_none()
    payload = data.model_dump(exclude_unset=True)

    if terms:
        for key, value in payload.items():
            setattr(terms, key, value)
        terms.updated_by = current_user.id
    else:
        terms = ClientContractTerms(
            client_id=client_id,
            updated_by=current_user.id,
            **payload,
        )
        db.add(terms)

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="contract_terms_updated",
            user_id=current_user.id,
            details={"fields": list(payload.keys())},
        )
    )
    await db.flush()
    await db.refresh(terms)
    return await _terms_to_response(db, terms)
