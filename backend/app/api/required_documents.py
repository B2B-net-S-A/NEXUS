"""Required documents — globalne szablony + per-klient instancje.

Routes are declared without a prefix so the router can be registered with
`prefix="/api"` in main.py — mirrors the client_materials pattern.

Templates (admin only):
  GET    /required-document-templates
  POST   /required-document-templates
  PATCH  /required-document-templates/{id}
  DELETE /required-document-templates/{id}

Per-klient instancje (jawny scope klienta/Joba do view, Admin/DL do edycji):
  GET    /clients/{client_id}/required-documents
  POST   /clients/{client_id}/required-documents              (ad-hoc, bez pliku)
  POST   /clients/{client_id}/required-documents/apply-templates  (bulk z szablonów)
  PATCH  /clients/{client_id}/required-documents/{id}
  DELETE /clients/{client_id}/required-documents/{id}
  POST   /clients/{client_id}/required-documents/{id}/upload  (multipart)
  GET    /clients/{client_id}/required-documents/{id}/download
"""

from datetime import datetime, timezone
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import OperationalUser, require_roles
from app.api.section_access import DeliverySectionUser
from app.core.database import get_db
from app.models.activity import Activity
from app.models.client import Client
from app.models.client_required_document import (
    ClientDocStatus,
    ClientRequiredDocument,
)
from app.models.required_document_template import RequiredDocumentTemplate
from app.models.user import User, UserRole
from app.schemas.required_documents import (
    ApplyTemplatesRequest,
    ClientRequiredDocumentCreate,
    ClientRequiredDocumentPatch,
    ClientRequiredDocumentResponse,
    RequiredDocumentTemplateCreate,
    RequiredDocumentTemplatePatch,
    RequiredDocumentTemplateResponse,
)
from app.services import storage_service
from app.services.client_access import deny, resolve_client_access


_admin_only = require_roles(UserRole.admin)

router = APIRouter()


MAX_UPLOAD_BYTES = 20 * 1024 * 1024  # 20 MB


# ── Helpers ──────────────────────────────────────────────────────────────────


async def _assert_client(db: AsyncSession, client_id: int) -> None:
    result = await db.execute(select(Client).where(Client.id == client_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Client not found")


async def _require_required_docs_access(
    db: AsyncSession,
    current_user: User,
    client_id: int,
    *,
    write: bool,
) -> None:
    access = await resolve_client_access(db, current_user, client_id)
    allowed = access.can_edit_materials if write else access.can_view_materials
    if not allowed:
        operation = "edycja" if write else "odczyt"
        raise deny(f"{operation} wymaganych dokumentów wymaga jawnego zakresu klienta")


async def require_required_docs_read_access(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    await _require_required_docs_access(
        db,
        current_user,
        client_id,
        write=False,
    )
    return current_user


async def require_required_docs_write_access(
    client_id: int,
    current_user: DeliverySectionUser,
    db: AsyncSession = Depends(get_db),
) -> User:
    await _assert_client(db, client_id)
    await _require_required_docs_access(
        db,
        current_user,
        client_id,
        write=True,
    )
    return current_user


RequiredDocsReadUser = Annotated[
    User,
    Depends(require_required_docs_read_access),
]
RequiredDocsWriteUser = Annotated[
    User,
    Depends(require_required_docs_write_access),
]


async def _resolve_user_email(
    db: AsyncSession, user_id: Optional[int]
) -> Optional[str]:
    if not user_id:
        return None
    return await db.scalar(select(User.email).where(User.id == user_id))


async def _doc_to_response(
    db: AsyncSession, doc: ClientRequiredDocument
) -> ClientRequiredDocumentResponse:
    email = await _resolve_user_email(db, doc.uploaded_by)
    return ClientRequiredDocumentResponse(
        id=doc.id,
        client_id=doc.client_id,
        template_id=doc.template_id,
        name=doc.name,
        description=doc.description,
        is_mandatory=doc.is_mandatory,
        status=doc.status,
        filename=doc.filename,
        content_type=doc.content_type,
        size_bytes=doc.size_bytes,
        uploaded_by=doc.uploaded_by,
        uploaded_by_email=email,
        uploaded_at=doc.uploaded_at,
        notes=doc.notes,
        created_at=doc.created_at,
        updated_at=doc.updated_at,
    )


# ── Templates ────────────────────────────────────────────────────────────────


@router.get(
    "/required-document-templates",
    response_model=List[RequiredDocumentTemplateResponse],
)
async def list_templates(
    current_user: OperationalUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(RequiredDocumentTemplate).order_by(
            RequiredDocumentTemplate.sort_order,
            RequiredDocumentTemplate.id,
        )
    )
    return list(result.scalars().all())


@router.post(
    "/required-document-templates",
    response_model=RequiredDocumentTemplateResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_template(
    payload: RequiredDocumentTemplateCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_only),
):
    tmpl = RequiredDocumentTemplate(
        **payload.model_dump(),
        created_by=current_user.id,
    )
    db.add(tmpl)
    await db.flush()
    await db.refresh(tmpl)
    return tmpl


@router.patch(
    "/required-document-templates/{template_id}",
    response_model=RequiredDocumentTemplateResponse,
)
async def patch_template(
    template_id: int,
    payload: RequiredDocumentTemplatePatch,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_only),
):
    result = await db.execute(
        select(RequiredDocumentTemplate).where(
            RequiredDocumentTemplate.id == template_id
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(tmpl, key, value)
    await db.flush()
    await db.refresh(tmpl)
    return tmpl


@router.delete(
    "/required-document-templates/{template_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_template(
    template_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(_admin_only),
):
    result = await db.execute(
        select(RequiredDocumentTemplate).where(
            RequiredDocumentTemplate.id == template_id
        )
    )
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Template not found")
    await db.delete(tmpl)
    await db.flush()
    return None


# ── Per-klient instances ─────────────────────────────────────────────────────


@router.get(
    "/clients/{client_id}/required-documents",
    response_model=List[ClientRequiredDocumentResponse],
)
async def list_required_docs(
    client_id: int,
    current_user: RequiredDocsReadUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientRequiredDocument)
        .where(ClientRequiredDocument.client_id == client_id)
        .order_by(ClientRequiredDocument.id)
    )
    docs = list(result.scalars().all())
    return [await _doc_to_response(db, d) for d in docs]


@router.post(
    "/clients/{client_id}/required-documents",
    response_model=ClientRequiredDocumentResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_required_doc(
    client_id: int,
    payload: ClientRequiredDocumentCreate,
    current_user: RequiredDocsWriteUser,
    db: AsyncSession = Depends(get_db),
):
    # Optional template lookup — only verify template exists if template_id provided
    if payload.template_id is not None:
        tmpl = await db.scalar(
            select(RequiredDocumentTemplate).where(
                RequiredDocumentTemplate.id == payload.template_id
            )
        )
        if not tmpl:
            raise HTTPException(status_code=404, detail="Template not found")

    doc = ClientRequiredDocument(
        client_id=client_id,
        template_id=payload.template_id,
        name=payload.name,
        description=payload.description,
        is_mandatory=payload.is_mandatory,
        notes=payload.notes,
    )
    db.add(doc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="required_doc_created",
            user_id=current_user.id,
            details={"name": payload.name, "template_id": payload.template_id},
        )
    )
    await db.flush()
    await db.refresh(doc)
    return await _doc_to_response(db, doc)


@router.post(
    "/clients/{client_id}/required-documents/apply-templates",
    response_model=List[ClientRequiredDocumentResponse],
    status_code=status.HTTP_201_CREATED,
)
async def apply_templates(
    client_id: int,
    payload: ApplyTemplatesRequest,
    current_user: RequiredDocsWriteUser,
    db: AsyncSession = Depends(get_db),
):
    """Bulk-utwórz instancje z szablonów. None = wszystkie is_default=true."""
    # Pick templates
    if payload.template_ids is None:
        result = await db.execute(
            select(RequiredDocumentTemplate)
            .where(RequiredDocumentTemplate.is_default.is_(True))
            .order_by(RequiredDocumentTemplate.sort_order)
        )
    else:
        if not payload.template_ids:
            return []
        result = await db.execute(
            select(RequiredDocumentTemplate).where(
                RequiredDocumentTemplate.id.in_(payload.template_ids)
            )
        )
    templates = list(result.scalars().all())

    # Skip templates already instantiated for this client
    existing = await db.execute(
        select(ClientRequiredDocument.template_id).where(
            ClientRequiredDocument.client_id == client_id,
            ClientRequiredDocument.template_id.is_not(None),
        )
    )
    already_applied = {row for row in existing.scalars().all()}

    created: list[ClientRequiredDocument] = []
    for tmpl in templates:
        if tmpl.id in already_applied:
            continue
        doc = ClientRequiredDocument(
            client_id=client_id,
            template_id=tmpl.id,
            name=tmpl.name,
            description=tmpl.description,
        )
        db.add(doc)
        created.append(doc)

    if created:
        db.add(
            Activity(
                entity_type="client",
                entity_id=client_id,
                action="required_docs_templates_applied",
                user_id=current_user.id,
                details={"template_ids": [d.template_id for d in created]},
            )
        )
        await db.flush()
        for d in created:
            await db.refresh(d)

    return [await _doc_to_response(db, d) for d in created]


@router.patch(
    "/clients/{client_id}/required-documents/{doc_id}",
    response_model=ClientRequiredDocumentResponse,
)
async def patch_required_doc(
    client_id: int,
    doc_id: int,
    payload: ClientRequiredDocumentPatch,
    current_user: RequiredDocsWriteUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientRequiredDocument).where(
            ClientRequiredDocument.id == doc_id,
            ClientRequiredDocument.client_id == client_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(doc, key, value)
    await db.flush()
    await db.refresh(doc)
    return await _doc_to_response(db, doc)


@router.delete(
    "/clients/{client_id}/required-documents/{doc_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_required_doc(
    client_id: int,
    doc_id: int,
    current_user: RequiredDocsWriteUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientRequiredDocument).where(
            ClientRequiredDocument.id == doc_id,
            ClientRequiredDocument.client_id == client_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.file_path:
        storage_service.delete_client_required_doc(doc.file_path)
    await db.delete(doc)
    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="required_doc_deleted",
            user_id=current_user.id,
            details={"name": doc.name, "filename": doc.filename},
        )
    )
    await db.flush()
    return None


@router.post(
    "/clients/{client_id}/required-documents/{doc_id}/upload",
    response_model=ClientRequiredDocumentResponse,
)
async def upload_required_doc_file(
    client_id: int,
    doc_id: int,
    current_user: RequiredDocsWriteUser,
    db: AsyncSession = Depends(get_db),
    file: UploadFile = File(...),
):
    result = await db.execute(
        select(ClientRequiredDocument).where(
            ClientRequiredDocument.id == doc_id,
            ClientRequiredDocument.client_id == client_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    filename = file.filename or "file"
    relative_path, size = storage_service.save_client_required_doc(
        client_id=client_id,
        upload_filename=filename,
        source=file.file,
    )
    if size > MAX_UPLOAD_BYTES:
        storage_service.delete_client_required_doc(relative_path)
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds {MAX_UPLOAD_BYTES // (1024 * 1024)} MB",
        )

    # Replace previous file if any
    if doc.file_path:
        storage_service.delete_client_required_doc(doc.file_path)

    doc.filename = filename
    doc.file_path = relative_path
    doc.content_type = file.content_type
    doc.size_bytes = size
    doc.uploaded_by = current_user.id
    doc.uploaded_at = datetime.now(timezone.utc)
    if doc.status == ClientDocStatus.pending:
        doc.status = ClientDocStatus.uploaded

    db.add(
        Activity(
            entity_type="client",
            entity_id=client_id,
            action="required_doc_uploaded",
            user_id=current_user.id,
            details={
                "name": doc.name,
                "filename": filename,
                "size_bytes": size,
            },
        )
    )
    await db.flush()
    await db.refresh(doc)
    return await _doc_to_response(db, doc)


@router.get(
    "/clients/{client_id}/required-documents/{doc_id}/download",
)
async def download_required_doc(
    client_id: int,
    doc_id: int,
    current_user: RequiredDocsReadUser,
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(ClientRequiredDocument).where(
            ClientRequiredDocument.id == doc_id,
            ClientRequiredDocument.client_id == client_id,
        )
    )
    doc = result.scalar_one_or_none()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path:
        raise HTTPException(status_code=404, detail="No file uploaded yet")

    try:
        abs_path = storage_service.get_client_required_doc_path(doc.file_path)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail="File missing on disk") from exc

    return FileResponse(
        path=str(abs_path),
        filename=doc.filename or "file",
        media_type=doc.content_type or "application/octet-stream",
    )
