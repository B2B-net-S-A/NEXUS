"""CV usuwanego kandydata zostają — także te trzymane w bazie (runda 9, R9-N7-12).

Decyzja Artura 26.09.2026: „nie usuwać nigdy żadnych CV”. ``DELETE
/api/candidates/{id}`` zostawiał pliki w magazynie obiektów, ale kaskada FK
kasowała wiersze, które trzymają CV WPROST w bazie (BYTEA): główne CV
w ``candidates.cv_file_content``, dokumenty sprzed migracji do magazynu,
oryginał i CV firmowe etapu oraz zatwierdzone wersje. Bajty znikały bez śladu,
a klucze plików w magazynie nie miały już żadnego wskaźnika.

Przed usunięciem wiersza każdy taki blob idzie do magazynu obiektów pod
neutralnym kluczem (bez nazwy pliku), a klucz każdego pliku tej osoby trafia
do ``retained_candidate_files`` pod pseudonimem. Magazyn niedostępny, a CV
w bazie jest = :class:`CvRetentionUnavailable` → handler odmawia usunięcia
(409) zamiast zgubić plik. Same klucze (bez bajtów) magazynu nie potrzebują,
więc takie usunięcie przechodzi jak dotąd.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from uuid import uuid4

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.retained_candidate_file import RetainedCandidateFile
from app.services import object_storage

logger = logging.getLogger(__name__)

# (źródło, zapytanie zwracające (bajty, typ treści)) — CV trzymane w bazie,
# które kaskada usunięcia kandydata by skasowała.
_BYTE_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "candidate_cv",
        "SELECT cv_file_content, NULL FROM candidates "
        "WHERE id = :cid AND cv_file_content IS NOT NULL AND cv_storage_key IS NULL",
    ),
    (
        "document",
        "SELECT file_content, content_type FROM candidate_documents "
        "WHERE candidate_id = :cid AND file_content IS NOT NULL "
        "AND storage_key IS NULL",
    ),
    (
        "stage_original",
        "SELECT original_cv_content, NULL FROM candidate_stage_cvs "
        "WHERE candidate_id = :cid AND original_cv_content IS NOT NULL "
        "AND original_cv_storage_key IS NULL",
    ),
    (
        "stage_branded",
        "SELECT branded_template_content, NULL FROM candidate_stage_cvs "
        "WHERE candidate_id = :cid AND branded_template_content IS NOT NULL",
    ),
    (
        "stage_version",
        "SELECT v.docx_content, NULL FROM cv_document_versions v "
        "JOIN candidate_stage_cvs s ON s.id = v.candidate_stage_cv_id "
        "WHERE s.candidate_id = :cid AND v.docx_content IS NOT NULL",
    ),
)

# Pliki zatwierdzonych wersji zapisane na dysku — wiersz znika kaskadą, plik
# zostaje; zapisujemy ścieżkę.
_PATH_SOURCES: tuple[tuple[str, str], ...] = (
    (
        "stage_version_path",
        "SELECT DISTINCT v.snapshot_path FROM cv_document_versions v "
        "JOIN candidate_stage_cvs s ON s.id = v.candidate_stage_cv_id "
        "WHERE s.candidate_id = :cid AND v.snapshot_path IS NOT NULL",
    ),
)


class CvRetentionUnavailable(Exception):
    """CV w bazie nie da się przenieść do magazynu — usunięcie musi poczekać."""


async def _blobs(
    db: AsyncSession, candidate_id: int
) -> list[tuple[str, bytes, str | None]]:
    out: list[tuple[str, bytes, str | None]] = []
    seen: set[str] = set()
    for source, sql in _BYTE_SOURCES:
        rows = (await db.execute(text(sql), {"cid": candidate_id})).all()
        for content, content_type in rows:
            if not content:
                continue
            data = bytes(content)
            digest = hashlib.sha256(data).hexdigest()
            if digest in seen:
                continue
            seen.add(digest)
            out.append((source, data, content_type))
    return out


async def retain_candidate_files(
    db: AsyncSession,
    candidate_id: int,
    *,
    subject_ref: str,
    storage_keys: list[str],
) -> int:
    """Zapisz wskaźniki do wszystkich CV osoby (przed ``db.delete``).

    Bajty z bazy wysyłane są do magazynu obiektów PRZED jakimkolwiek zapisem
    w bazie; nieudane wysłanie przerywa usunięcie. Zwraca liczbę wpisów.
    """
    blobs = await _blobs(db, candidate_id)
    if blobs and not object_storage.is_available():
        raise CvRetentionUnavailable("object_storage_unavailable")

    rows: list[RetainedCandidateFile] = []
    for source, data, content_type in blobs:
        digest = hashlib.sha256(data).hexdigest()
        key = f"retained-cv/{subject_ref[:16]}/{digest[:16]}-{uuid4().hex[:8]}"
        try:
            await asyncio.to_thread(
                object_storage.upload_cv,
                data,
                "cv",
                content_type,
                storage_key=key,
            )
        except Exception as exc:  # noqa: BLE001 — każda awaria = brak kopii
            logger.warning(
                "[cv_retention] upload failed source=%s: %s",
                source,
                type(exc).__name__,
            )
            raise CvRetentionUnavailable("object_storage_upload_failed") from exc
        rows.append(
            RetainedCandidateFile(
                subject_ref=subject_ref,
                source=source,
                storage_key=key,
                content_type=content_type,
                size_bytes=len(data),
                content_sha256=digest,
            )
        )

    for key in sorted({k for k in storage_keys if k}):
        rows.append(
            RetainedCandidateFile(
                subject_ref=subject_ref, source="storage_key", storage_key=key[:512]
            )
        )
    for source, sql in _PATH_SOURCES:
        for (path,) in (await db.execute(text(sql), {"cid": candidate_id})).all():
            if path:
                rows.append(
                    RetainedCandidateFile(
                        subject_ref=subject_ref, source=source, storage_key=path[:512]
                    )
                )
    db.add_all(rows)
    return len(rows)
