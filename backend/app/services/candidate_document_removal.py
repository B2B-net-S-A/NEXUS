"""„Usuń z profilu” — plik kandydata znika z ekranów, a zostaje w magazynie (0435).

Decyzja Artura 13.10.2026: admin i Head of Recruitment mogą usunąć plik
z profilu kandydata. Obowiązuje też decyzja z 26.09.2026 („nie usuwać nigdy
żadnych CV”), więc nic nie jest kasowane: wiersz dostaje `source_deleted_at`
(wspólny wyłącznik, który respektują lista plików, podgląd, generator, QC
i migawka CV etapu) oraz `removed_at` / `removed_by`.

Kandydat trzyma też własny wskaźnik CV sprzed listy plików (`cv_filename`,
`cv_storage_key`, `cv_file_content`). `get_current_cv` wraca do niego, gdy nie
znajdzie dokumentu, a `entrypoint.sh` przy każdym wdrożeniu odtwarza z niego
wiersz dokumentu. Jeśli wskaźnik pokazuje na usuwany plik, trzeba go odpiąć —
inaczej „usunięte” CV szłoby dalej do migawki CV etapu i paczki ZIP, a po
wdrożeniu wróciłoby na listę jako główne.

Import z Traffita wgrywał to samo CV DWA razy pod różnymi kluczami (wskaźnik
kandydata i wiersz dokumentu) — 13.10.2026 tak miało 55 017 z 62 216
wskaźników. Dlatego ten sam plik poznajemy też po nazwie, a drugą kopię
zapisujemy jako osobny usunięty wiersz: klucz nie traci jedynego wskaźnika.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind

# Wiersz utworzony ze wskaźnika kandydata w chwili usuwania pliku.
POINTER_COPY_SOURCE = "legacy_pointer"


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

    await _detach_candidate_cv_pointer(
        db, candidate=candidate, document=document, removed_at=now, actor_id=actor_id
    )


async def _detach_candidate_cv_pointer(
    db: AsyncSession,
    *,
    candidate: Candidate,
    document: CandidateDocument,
    removed_at: datetime,
    actor_id: int,
) -> None:
    """Wskaźnik CV na kandydacie nie może dalej pokazywać usuniętego pliku."""

    live = (
        await db.execute(
            select(
                CandidateDocument.filename,
                CandidateDocument.storage_key,
                CandidateDocument.is_primary,
                CandidateDocument.document_kind,
            ).where(
                CandidateDocument.candidate_id == candidate.id,
                CandidateDocument.id != document.id,
                CandidateDocument.source_deleted_at.is_(None),
            )
        )
    ).all()
    live_keys = {row.storage_key for row in live if row.storage_key}
    if not await _pointer_is_removed_file(db, candidate, document, live_keys):
        return

    pointer_key = candidate.cv_storage_key
    if pointer_key and pointer_key != document.storage_key:
        db.add(
            CandidateDocument(
                candidate_id=candidate.id,
                filename=(candidate.cv_filename or document.filename)[:500],
                storage_key=pointer_key,
                content_type=document.content_type,
                document_kind=document.document_kind,
                is_primary=False,
                external_source=POINTER_COPY_SOURCE,
                source_deleted_at=removed_at,
                removed_at=removed_at,
                removed_by=actor_id,
            )
        )

    successor = next(
        (
            row
            for row in live
            if row.is_primary and row.document_kind == CandidateDocumentKind.cv
        ),
        None,
    )
    candidate.cv_filename = successor.filename if successor else None
    candidate.cv_storage_key = successor.storage_key if successor else None
    # Bezpieczne: bajty w wierszu kandydata są tu albo puste, albo te same,
    # które zostają przy dokumencie (`_pointer_is_removed_file`).
    candidate.cv_file_content = None


async def _pointer_is_removed_file(
    db: AsyncSession,
    candidate: Candidate,
    document: CandidateDocument,
    live_keys: set[str],
) -> bool:
    """Czy wskaźnik CV kandydata pokazuje na usuwany plik."""

    if candidate.cv_file_content is not None:
        # Bajty rozstrzygają same. Zdejmujemy je tylko wtedy, gdy ten sam plik
        # zostaje przy dokumencie — inaczej zginęłoby CV.
        same_bytes = (
            bool(document.content_sha256)
            and hashlib.sha256(bytes(candidate.cv_file_content)).hexdigest()
            == document.content_sha256
        )
        return same_bytes and await _document_keeps_bytes(db, document)

    pointer_key = candidate.cv_storage_key
    if pointer_key:
        if pointer_key == document.storage_key:
            return True
        if pointer_key in live_keys:
            # Wskaźnik innego pliku, który zostaje w profilu.
            return False
    return (
        bool(candidate.cv_filename)
        and candidate.cv_filename.lower() == document.filename.lower()
    )


async def _document_keeps_bytes(db: AsyncSession, document: CandidateDocument) -> bool:
    if document.storage_key:
        return True
    return bool(
        await db.scalar(
            select(CandidateDocument.file_content.is_not(None)).where(
                CandidateDocument.id == document.id
            )
        )
    )
