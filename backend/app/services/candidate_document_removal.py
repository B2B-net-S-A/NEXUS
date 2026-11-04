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

# Jak w `cv_source`: te rodzaje nigdy nie są bieżącym CV.
_NOT_CV_KINDS = (CandidateDocumentKind.certificate, CandidateDocumentKind.cover_letter)


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
    actor_id: int | None,
) -> None:
    """Wskaźnik CV na kandydacie nie może dalej pokazywać usuniętego pliku.

    Nazwa i klucz to dwa osobne fakty: nowe główne CV zmienia we wskaźniku
    samą nazwę, a kwarantanna tożsamości samą nazwę czyści. Dlatego każdy
    rozstrzygamy osobno.
    """
    same_bytes = False
    if candidate.cv_file_content is not None:
        same_bytes = await _document_holds_same_bytes(db, candidate, document)
        if not same_bytes:
            # Bajty innego pliku albo jedyna kopia tych samych — nie ruszamy.
            return

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
    pointer_name = (candidate.cv_filename or "").strip()
    names_removed_file = pointer_name.lower() == document.filename.lower()
    pointer_key = candidate.cv_storage_key

    key_owner = next(
        (row for row in live if pointer_key and row.storage_key == pointer_key), None
    )
    if key_owner is not None:
        # Klucz innego pliku, który zostaje w profilu. Nazwa mogła już przejść
        # na usuwany plik (wgranie nowego głównego CV zmienia samą nazwę).
        if names_removed_file:
            candidate.cv_filename = key_owner.filename
        candidate.cv_file_content = None
        return

    # Klucz, którego nie ma żaden plik z listy: druga kopia usuwanego pliku,
    # gdy wskaźnik nosi jego nazwę albo nie ma nazwy wcale.
    twin_key = bool(pointer_key) and pointer_key != document.storage_key
    nameless_cv_twin = (
        twin_key and not pointer_name and document.document_kind not in _NOT_CV_KINDS
    )
    if not (
        same_bytes
        or names_removed_file
        or nameless_cv_twin
        or (pointer_key and pointer_key == document.storage_key)
    ):
        return

    if twin_key:
        db.add(
            CandidateDocument(
                candidate_id=candidate.id,
                filename=(pointer_name or document.filename)[:500],
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
    candidate.cv_file_content = None


async def _document_holds_same_bytes(
    db: AsyncSession, candidate: Candidate, document: CandidateDocument
) -> bool:
    """Bajty CV z wiersza kandydata wolno zdjąć tylko wtedy, gdy ten sam plik
    zostaje przy dokumencie (magazyn albo BYTEA) — inaczej zginęłoby CV."""

    if (
        not document.content_sha256
        or hashlib.sha256(bytes(candidate.cv_file_content)).hexdigest()
        != document.content_sha256
    ):
        return False
    if document.storage_key:
        return True
    return bool(
        await db.scalar(
            select(CandidateDocument.file_content.is_not(None)).where(
                CandidateDocument.id == document.id
            )
        )
    )
