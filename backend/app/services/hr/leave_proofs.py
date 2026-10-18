"""Załącznik do wniosku urlopowego — potwierdzenie nieobecności w e-teczce.

Compass miał przy wniosku plik do 5 MB (``uploadLeaveProof``). W NEXUSIE plik
jest dokumentem e-teczki osoby (``hr_documents``, rodzaj ``absence_proof``)
z odnośnikiem ``leave_request_id`` — Kadry widzą go też w kartotece, a okres
przechowywania liczy ``documents_retention`` jak dla innych dokumentów.

* Dołącza sama osoba do własnego wniosku — przy składaniu albo później
  z „Moje nieobecności” (oczekujący albo zatwierdzony; do odrzuconego
  i anulowanego nie). Typowo: urlop okolicznościowy (akt ślubu, urodzenia,
  zgonu), opieka nad dzieckiem, krwiodawstwo. L4 przychodzi przez e-ZLA —
  bez wymogu, ale też bez zakazu.
* Plik: PDF, JPG albo PNG do 5 MB, typ rozpoznany po treści
  (``documents_store``), nazwa od człowieka tylko w bazie, na dysku skrót.
* Krąg: osoba i Kadry (admin). Przełożony i zastępca widzą przy wniosku
  tylko liczbę załączników (``proof_count``) — treść bywa aktem zgonu albo
  dokumentem dziecka (D6), pobrać jej nie mogą (404).
* Usunąć może osoba plik, który sama dodała (pomyłka); ślad zostaje
  w e-teczce jak przy usunięciu przez Kadry.

Funkcje nie commitują — robi to trasa; plik do skasowania wraca do trasy
i znika z dysku po commicie (``documents.delete_files``).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import Any, Iterable, Optional

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.hr_document import HrDocument
from app.models.hr_leave import LeaveRequest
from app.models.user import User
from app.services.hr import audit, documents, documents_store
from app.services.hr.documents import HrDocumentError
from app.services.hr.leave_policy import type_label
from app.services.hr.leave_recipients import format_range
from app.services.hr_leave_schema import ACTIVE_STATUSES

KIND = "absence_proof"
MAX_PROOF_BYTES = 5 * 1024 * 1024
MAX_PROOFS_PER_REQUEST = 5
PROOF_MIME_TYPES: tuple[str, ...] = ("application/pdf", "image/jpeg", "image/png")
#: Rodzaje, przy których okno podpowiada załącznik (front ma lustro).
SUGGESTED_TYPES: tuple[str, ...] = ("occasional", "childcare", "blood_donation")
REMOVED_NOTE = "Usunięty przez osobę przy wniosku urlopowym."

NOT_FOUND = "Nie ma takiego załącznika."


def _check_file(content: bytes) -> tuple[str, str]:
    if not content:
        raise HrDocumentError("Plik jest pusty.")
    if len(content) > MAX_PROOF_BYTES:
        raise HrDocumentError("Załącznik może mieć najwyżej 5 MB.")
    try:
        mime, digest = documents_store.check(content)
    except documents_store.FileRejected as exc:
        raise HrDocumentError(str(exc)) from None
    if mime not in PROOF_MIME_TYPES:
        raise HrDocumentError("Dołącz PDF albo zdjęcie (JPG, PNG).")
    return mime, digest


async def _live(db: AsyncSession, request_id: uuid.UUID) -> list[HrDocument]:
    return list(
        await db.scalars(
            select(HrDocument)
            .where(
                HrDocument.leave_request_id == request_id,
                HrDocument.deleted_at.is_(None),
            )
            .order_by(HrDocument.created_at, HrDocument.id)
        )
    )


async def attach(
    db: AsyncSession,
    *,
    request: LeaveRequest,
    content: bytes,
    file_name: Optional[str],
    actor: User,
) -> HrDocument:
    """Dołącza plik do wniosku osoby (wołający sprawdził, że to jej wniosek)."""

    if request.status not in ACTIVE_STATUSES:
        raise HrDocumentError(
            "Do odrzuconego albo anulowanego wniosku nie dołącza się plików.", 409
        )
    if len(await _live(db, request.id)) >= MAX_PROOFS_PER_REQUEST:
        raise HrDocumentError(
            f"Do wniosku można dołączyć najwyżej {MAX_PROOFS_PER_REQUEST} plików.", 409
        )
    mime, digest = _check_file(content)
    duplicate = await db.scalar(
        select(HrDocument.id).where(
            HrDocument.user_id == request.user_id,
            HrDocument.sha256 == digest,
            HrDocument.source == "upload",
            HrDocument.deleted_at.is_(None),
        )
    )
    if duplicate is not None:
        raise HrDocumentError("Ten plik jest już w Twoich dokumentach.", 409)
    path = documents_store.save(request.user_id, content, mime=mime, digest=digest)
    title = (
        f"{type_label(request.leave_type, None)} "
        f"{format_range(request.start_date, request.end_date)}"
    )
    document = HrDocument(
        user_id=request.user_id,
        kind=KIND,
        purpose=None,
        title=title,
        source="upload",
        source_ref=None,
        leave_request_id=request.id,
        file_path=path,
        file_name=documents.clean_file_name(file_name),
        mime=mime,
        size_bytes=len(content),
        sha256=digest,
        valid_until=None,
        visible_to_person=True,
        visible_to_payroll=False,
        visible_to_equipment=False,
        added_by=actor.id,
    )
    try:
        async with db.begin_nested():
            db.add(document)
            await db.flush()
    except IntegrityError:
        raise HrDocumentError("Ten plik jest już w Twoich dokumentach.", 409) from None
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="leave_proof_attached",
        details={"leave_request_id": str(request.id)},
        sensitivity="health",
    )
    return document


async def proof_of(
    db: AsyncSession, request: LeaveRequest, document_id: int
) -> HrDocument:
    """Żywy załącznik tego wniosku albo 404."""

    document = await db.get(HrDocument, document_id)
    if (
        document is None
        or document.leave_request_id != request.id
        or document.deleted_at is not None
    ):
        raise HrDocumentError(NOT_FOUND, 404)
    return document


async def remove_own(
    db: AsyncSession, request: LeaveRequest, document: HrDocument, *, actor: User
) -> Optional[str]:
    """Osoba zdejmuje plik, który sama dodała; zwraca plik do skasowania."""

    if document.added_by != actor.id:
        raise HrDocumentError("Ten plik dodały Kadry — usunąć go mogą tylko one.", 403)
    orphan = await documents.mark_deleted(
        db, document, reason="mistake", note=REMOVED_NOTE, actor_id=actor.id
    )
    audit.record(
        db,
        actor_user_id=actor.id,
        subject_user_id=request.user_id,
        entity_type="hr_document",
        entity_id=document.id,
        action="leave_proof_removed",
        details={"leave_request_id": str(request.id)},
        sensitivity="health",
    )
    return orphan


async def proofs_by_request(
    db: AsyncSession, request_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, list[HrDocument]]:
    """Żywe załączniki wielu wniosków — jedno zapytanie."""

    ids = list(request_ids)
    if not ids:
        return {}
    rows = await db.scalars(
        select(HrDocument)
        .where(
            HrDocument.leave_request_id.in_(ids),
            HrDocument.deleted_at.is_(None),
        )
        .order_by(HrDocument.created_at, HrDocument.id)
    )
    grouped: dict[uuid.UUID, list[HrDocument]] = defaultdict(list)
    for row in rows:
        if row.leave_request_id is not None:
            grouped[row.leave_request_id].append(row)
    return grouped


async def proof_counts(
    db: AsyncSession, request_ids: Iterable[uuid.UUID]
) -> dict[uuid.UUID, int]:
    ids = list(request_ids)
    if not ids:
        return {}
    rows = await db.execute(
        select(HrDocument.leave_request_id, func.count())
        .where(
            HrDocument.leave_request_id.in_(ids),
            HrDocument.deleted_at.is_(None),
        )
        .group_by(HrDocument.leave_request_id)
    )
    return {request_id: count for request_id, count in rows.all()}


def proof_payload(document: HrDocument, *, viewer_id: int) -> dict[str, Any]:
    return {
        "id": document.id,
        "file_name": documents.download_name(document),
        "mime": document.mime,
        "size_bytes": document.size_bytes,
        "created_at": document.created_at.isoformat() if document.created_at else None,
        "can_remove": document.added_by == viewer_id,
    }


__all__ = [
    "KIND",
    "MAX_PROOFS_PER_REQUEST",
    "MAX_PROOF_BYTES",
    "PROOF_MIME_TYPES",
    "SUGGESTED_TYPES",
    "attach",
    "proof_counts",
    "proof_of",
    "proof_payload",
    "proofs_by_request",
    "remove_own",
]
