"""„Usuń z profilu” — plik kandydata znika z ekranów, a zostaje w magazynie (0435).

Decyzja Artura 13.10.2026: admin i Head of Recruitment mogą usunąć plik
z profilu kandydata. Obowiązuje też decyzja z 26.09.2026 („nie usuwać nigdy
żadnych CV”), więc nic nie jest kasowane: wiersz dostaje `source_deleted_at`
(wspólny wyłącznik, który respektują lista plików, podgląd, generator, QC
i migawka CV etapu) oraz `removed_at` / `removed_by`.

Kandydat trzyma też własny wskaźnik CV sprzed listy plików (`cv_filename`,
`cv_storage_key`, `cv_file_content`), a `get_current_cv` wraca do niego, gdy
nie znajdzie dokumentu. Jeśli wskaźnik pokazuje na usuwany plik, trzeba go
odpiąć — inaczej generator dalej brałby „usunięte” CV. Bajty nie giną: ten sam
plik zostaje przy wierszu dokumentu.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind


async def remove_candidate_document(
    db: AsyncSession,
    *,
    candidate: Candidate,
    document: CandidateDocument,
    actor_id: int,
) -> None:
    """Oznacz plik jako usunięty z profilu. Nie commituje.

    Główne CV też wolno usunąć. Następcy nie wybieramy sami: nowe główne CV
    odświeża profil odczytem AI, a jedynym innym CV bywa plik „…B2B…”
    przygotowany dla klienta. Profil zostaje bez głównego CV, dopóki ktoś nie
    wskaże innego pliku albo nie wgra nowego.
    """
    now = datetime.now(timezone.utc)
    document.is_primary = False
    document.source_deleted_at = now
    document.removed_at = now
    document.removed_by = actor_id

    await _detach_candidate_cv_pointer(db, candidate=candidate, document=document)


async def _detach_candidate_cv_pointer(
    db: AsyncSession, *, candidate: Candidate, document: CandidateDocument
) -> None:
    """Wskaźnik CV na kandydacie nie może dalej pokazywać usuniętego pliku."""

    remaining_primary = (
        await db.execute(
            select(CandidateDocument.filename, CandidateDocument.storage_key)
            .where(
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.id != document.id,
                CandidateDocument.document_kind == CandidateDocumentKind.cv,
                CandidateDocument.is_primary.is_(True),
                CandidateDocument.source_deleted_at.is_(None),
            )
            .limit(1)
        )
    ).first()

    if candidate.cv_filename and candidate.cv_filename == document.filename:
        candidate.cv_filename = (
            remaining_primary.filename if remaining_primary else None
        )
    if candidate.cv_storage_key and candidate.cv_storage_key == document.storage_key:
        candidate.cv_storage_key = (
            remaining_primary.storage_key if remaining_primary else None
        )
    if (
        candidate.cv_file_content is not None
        and document.content_sha256
        and hashlib.sha256(bytes(candidate.cv_file_content)).hexdigest()
        == document.content_sha256
        and await _document_keeps_bytes(db, document)
    ):
        candidate.cv_file_content = None


async def _document_keeps_bytes(db: AsyncSession, document: CandidateDocument) -> bool:
    """Kopię CV z wiersza kandydata zdejmujemy tylko wtedy, gdy ten sam plik
    zostaje przy dokumencie (magazyn albo BYTEA) — inaczej zginęłyby bajty."""

    if document.storage_key:
        return True
    return bool(
        await db.scalar(
            select(CandidateDocument.file_content.is_not(None)).where(
                CandidateDocument.id == document.id
            )
        )
    )
