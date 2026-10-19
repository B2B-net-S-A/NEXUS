"""Dokumenty osoby (e-teczka) — trasy, prefiks ``/api/hr/documents`` (etap 5, E4).

Moduł „Ludzie” (``HrModule.people``) — wyłączony = 404 poza adminem. Bramki:

* ``require_hr_documents_reader`` — e-teczkę osoby czytają Kadry i admin
  (całość), sama osoba, Płace i recepcja (dokumenty ze swoim znacznikiem;
  protokoły sprzętu — osoba, Kadry, recepcja). Przełożony i reszta: 404,
  bez zdradzania, że coś jest,
* ``require_hr_documents_admin`` — wgranie, zmiana, usunięcie pomyłki,
  retencja i jej okresy: Kadry (admin ma je zawsze).

Trasy:

* ``GET  /people/{user_id}`` — lista dokumentów i protokołów osoby,
* ``POST /people/{user_id}`` — wgranie (multipart),
* ``GET  /people/{user_id}/protocols/{protocol_id}/file`` — plik protokołu,
* ``GET  /{document_id}/file`` — plik dokumentu,
* ``PATCH /{document_id}`` — tytuł, „ważny do”, krąg,
* ``POST /{document_id}/remove`` — usunięcie pomyłki z powodem,
* ``GET  /retention`` i ``POST /retention/delete`` — lista po terminie
  i usunięcie zaznaczonych (z potwierdzeniem),
* ``GET``/``PUT /settings/retention`` — okresy przechowywania na rodzaj.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from typing import Any, Iterator, Literal, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_onboarded_user
from app.api.hr_gates import ensure_module
from app.core.database import get_db
from app.core.http_headers import content_disposition, safe_document_disposition
from app.models.user import User
from app.services.action_permissions import ProductAction
from app.services.hr import (
    audit,
    documents,
    documents_protocols,
    documents_retention,
    documents_rules,
    people,
)
from app.services.hr import modules as hr_modules
from app.services.hr.modules import HrModule
from app.services.hr_documents_schema import (
    DOCUMENT_KINDS,
    MAX_FILE_BYTES,
    NOTE_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from app.services.permission_denial import ensure_any_permission

router = APIRouter()

PERSON_NOT_FOUND = "Nie ma takiej kartoteki."


# ── Bramki ────────────────────────────────────────────────────────────────────


def require_hr_documents_reader():
    """Moduł „Ludzie” włączony; zakres osoby i dokumentu rozstrzyga serwis."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.people)
        return current_user

    return _check


def require_hr_documents_admin():
    """Moduł „Ludzie” włączony i uprawnienie „Kadry” (admin ma je zawsze)."""

    async def _check(
        current_user: User = Depends(require_onboarded_user),
        db: AsyncSession = Depends(get_db),
    ) -> User:
        await ensure_module(db, current_user, HrModule.people)
        ensure_any_permission(current_user, ProductAction.people_admin)
        return current_user

    _check.required_permissions = (ProductAction.people_admin,)
    return _check


_reader = require_hr_documents_reader()
_admin = require_hr_documents_admin()


@contextmanager
def _http_errors() -> Iterator[None]:
    try:
        yield
    except documents.HrDocumentError as exc:
        raise HTTPException(exc.status_code, exc.message) from None
    except documents_rules.RetentionSettingsError as exc:
        raise HTTPException(422, str(exc)) from None
    except people.HrPeopleError as exc:
        raise HTTPException(422, str(exc)) from None


# ── Lista osoby ───────────────────────────────────────────────────────────────


async def _person_or_404(
    db: AsyncSession, user_id: int, viewer: documents.Viewer
) -> None:
    if not documents.can_read_person(viewer, user_id):
        raise HTTPException(404, PERSON_NOT_FOUND)
    if await db.get(User, user_id) is None:
        raise HTTPException(404, PERSON_NOT_FOUND)
    if not viewer.manage and await people.profile_of(db, user_id) is None:
        raise HTTPException(404, PERSON_NOT_FOUND)


async def _protocols_open(db: AsyncSession, user: User) -> bool:
    loaded = await hr_modules.load_modules(db)
    return hr_modules.module_open_for(user, loaded, HrModule.equipment)


@router.get("/people/{user_id}")
async def person_documents(
    user_id: int,
    current_user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    viewer = documents.viewer_of(current_user)
    await _person_or_404(db, user_id, viewer)
    rows = await documents.documents_of(db, user_id, viewer)
    names = await documents.names_of(
        db, [value for row in rows for value in (row.added_by, row.deleted_by)]
    )
    protocols = None
    if documents.sees_protocols(viewer, user_id) and await _protocols_open(
        db, current_user
    ):
        protocols = [
            documents_protocols.protocol_payload(protocol)
            for protocol in await documents_protocols.protocols_of(db, user_id)
        ]
    return {
        "user_id": user_id,
        "can_manage": viewer.manage,
        "documents": [documents.payload(row, viewer, names) for row in rows],
        "protocols": protocols,
    }


def _form_bool(value: Optional[str]) -> Optional[bool]:
    if value is None or value == "":
        return None
    if value.lower() in {"true", "1", "on", "tak"}:
        return True
    if value.lower() in {"false", "0", "off", "nie"}:
        return False
    raise HTTPException(422, "Krąg widzących: wartość tak albo nie.")


def _form_date(value: Optional[str]) -> Optional[date]:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        raise HTTPException(422, "Data „ważny do” w formacie RRRR-MM-DD.") from None


def _sync_payload(sync: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if sync is None:
        return None
    until = sync.get("until")
    return {"status": sync["status"], "until": until.isoformat() if until else None}


@router.post("/people/{user_id}", status_code=201)
async def upload_document(
    user_id: int,
    file: UploadFile = File(...),
    kind: str = Form(...),
    title: str = Form(..., max_length=TITLE_MAX_LENGTH * 2),
    valid_until: Optional[str] = Form(None),
    purpose: Optional[str] = Form(None),
    visible_to_person: Optional[str] = Form(None),
    visible_to_payroll: Optional[str] = Form(None),
    visible_to_equipment: Optional[str] = Form(None),
    current_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    content = await file.read(MAX_FILE_BYTES + 1)
    flags = (
        _form_bool(visible_to_person),
        _form_bool(visible_to_payroll),
        _form_bool(visible_to_equipment),
    )
    with _http_errors():
        if kind not in DOCUMENT_KINDS:
            raise documents.HrDocumentError("Nieznany rodzaj dokumentu.")
        audience = None
        if any(flag is not None for flag in flags):
            default = documents.default_audience(kind)
            person, payroll, equipment = (
                default.person if flags[0] is None else flags[0],
                default.payroll if flags[1] is None else flags[1],
                default.equipment if flags[2] is None else flags[2],
            )
            audience = documents.Audience(
                person=person, payroll=payroll, equipment=equipment
            )
        document, sync = await documents.upload(
            db,
            user_id=user_id,
            kind=kind,
            title=title,
            content=content,
            file_name=file.filename,
            valid_until=_form_date(valid_until),
            purpose=(purpose or None),
            audience=audience,
            actor=current_user,
        )
    viewer = documents.viewer_of(current_user)
    names = await documents.names_of(db, [document.added_by])
    return {
        "document": documents.payload(document, viewer, names),
        "profile_sync": _sync_payload(sync),
    }


@router.get("/people/{user_id}/protocols/{protocol_id}/file")
async def person_protocol_file(
    user_id: int,
    protocol_id: int,
    current_user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> Response:
    viewer = documents.viewer_of(current_user)
    await _person_or_404(db, user_id, viewer)
    if not documents.sees_protocols(viewer, user_id) or not await _protocols_open(
        db, current_user
    ):
        raise HTTPException(404, "Nie ma takiego protokołu.")
    with _http_errors():
        protocol = await documents_protocols.protocol_of_person(
            db, user_id, protocol_id
        )
        found = await documents_protocols.protocol_file(db, protocol)
    disposition = content_disposition(found.filename)
    if found.path is not None:
        return FileResponse(
            found.path,
            media_type=found.media_type,
            headers={"Content-Disposition": disposition},
        )
    return Response(
        found.content or b"",
        media_type=found.media_type,
        headers={"Content-Disposition": disposition},
    )


# ── Dokument ──────────────────────────────────────────────────────────────────


@router.get("/{document_id}/file")
async def document_file(
    document_id: int,
    disposition: Literal["attachment", "inline"] = Query("attachment"),
    current_user: User = Depends(_reader),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    viewer = documents.viewer_of(current_user)
    with _http_errors():
        document = await documents.readable_document(db, document_id, viewer)
        path = documents.file_of(document)
    # Kto otworzył plik e-teczki (także podgląd) — ślad w ``hr_audit_events``;
    # zapisuje go commit sesji żądania (``get_db``) przed wysłaniem pliku.
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=document.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="document_downloaded",
        details={"kind": document.kind},
        sensitivity="health" if document.kind == documents.ABSENCE_PROOF else "general",
    )
    return FileResponse(
        path,
        media_type=document.mime,
        headers={
            "Content-Disposition": content_disposition(
                documents.download_name(document),
                safe_document_disposition(document.mime, disposition),
            )
        },
    )


class AudienceIn(BaseModel):
    person: bool
    payroll: bool
    equipment: bool


class DocumentPatchIn(BaseModel):
    title: Optional[str] = Field(None, max_length=TITLE_MAX_LENGTH * 2)
    valid_until: Optional[date] = None
    audience: Optional[AudienceIn] = None


@router.patch("/{document_id}")
async def patch_document(
    document_id: int,
    body: DocumentPatchIn,
    current_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    sent = body.model_fields_set
    with _http_errors():
        document = await documents.get_document(db, document_id)
        kwargs: dict[str, Any] = {}
        if "title" in sent:
            kwargs["title"] = body.title
        if "valid_until" in sent:
            kwargs["valid_until"] = body.valid_until
        if body.audience is not None:
            kwargs["audience"] = documents.Audience(
                person=body.audience.person,
                payroll=body.audience.payroll,
                equipment=body.audience.equipment,
            )
        document, sync = await documents.update(
            db, document, actor=current_user, **kwargs
        )
    viewer = documents.viewer_of(current_user)
    names = await documents.names_of(db, [document.added_by])
    return {
        "document": documents.payload(document, viewer, names),
        "profile_sync": _sync_payload(sync),
    }


class RemoveIn(BaseModel):
    note: str = Field(..., max_length=NOTE_MAX_LENGTH * 2)


@router.post("/{document_id}/remove")
async def remove_document(
    document_id: int,
    body: RemoveIn,
    current_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        document = await documents.get_document(db, document_id)
        orphan = await documents.remove(
            db, document, note=body.note, actor=current_user
        )
    await db.commit()
    documents.delete_files([orphan])
    return {"id": document_id, "deleted": True}


# ── Retencja ──────────────────────────────────────────────────────────────────


@router.get("/retention")
async def retention_due(
    _: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    items = await documents_retention.due(db)
    years = await documents_rules.load_retention(db)
    return {
        "items": [documents_retention.due_payload(item) for item in items],
        "retention": documents_rules.retention_payload(years),
    }


class RetentionDeleteIn(BaseModel):
    document_ids: list[int] = Field(
        ..., min_length=1, max_length=documents_retention.MAX_BATCH
    )
    #: Potwierdzenie w oknie — bez niego nic nie znika.
    confirm: Literal[True]


@router.post("/retention/delete")
async def retention_delete(
    body: RetentionDeleteIn,
    current_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    deleted, skipped, orphans = await documents_retention.delete_due(
        db, body.document_ids, actor_id=current_user.id
    )
    await db.commit()
    documents.delete_files(orphans)
    return {"deleted": deleted, "skipped": skipped}


class RetentionSettingsIn(BaseModel):
    years: dict[str, int]


@router.get("/settings/retention")
async def get_retention_settings(
    _: User = Depends(_admin), db: AsyncSession = Depends(get_db)
) -> dict[str, Any]:
    years = await documents_rules.load_retention(db)
    return {"retention": documents_rules.retention_payload(years)}


@router.put("/settings/retention")
async def put_retention_settings(
    body: RetentionSettingsIn,
    current_user: User = Depends(_admin),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    with _http_errors():
        years = await documents_rules.save_retention(
            db, body.years, actor_id=current_user.id
        )
    audit.record(
        db,
        actor_user_id=current_user.id,
        subject_user_id=None,
        entity_type="hr_document_retention",
        entity_id=documents_rules.RETENTION_SETTING,
        action="document_retention_changed",
        details={"years": years},
    )
    return {"retention": documents_rules.retention_payload(years)}
