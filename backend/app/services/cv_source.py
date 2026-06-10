"""Single source of truth for "the candidate's current CV file".

After the Object Storage migration (0079/0080 + finalize-delete-bytea) the
legacy ``Candidate.cv_file_content`` BYTEA is NULL for every candidate, and
the real CV lives either in ``candidate_documents`` (storage_key → Hetzner
Object Storage, or legacy ``file_content``) or under ``Candidate.cv_storage_key``.

Every consumer that needs CV bytes (stage snapshots, the B2B CV generator,
future exports) should resolve them through :func:`get_current_cv` instead of
reading ``cv_file_content`` directly — that column silently went dark and
broke per-stage CV snapshots for weeks.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument
from app.services import object_storage

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CurrentCV:
    content: bytes
    filename: str
    language: str | None
    source: str  # 'document_storage' | 'document_bytea' | 'candidate_storage' | 'candidate_bytea'


async def get_current_cv(
    db: AsyncSession, candidate: Candidate
) -> CurrentCV | None:
    """Resolve the candidate's current CV bytes, wherever they live.

    Priority: primary/most-recent ``CandidateDocument`` (object storage, then
    legacy BYTEA) → ``Candidate.cv_storage_key`` → legacy
    ``Candidate.cv_file_content``. Object-storage downloads run in a worker
    thread (boto3 is sync). Returns ``None`` when the candidate has no CV.
    """
    doc = (
        await db.scalars(
            select(CandidateDocument)
            .where(
                CandidateDocument.candidate_id == candidate.id,
                or_(
                    func.lower(CandidateDocument.filename).like("%.pdf"),
                    func.lower(CandidateDocument.filename).like("%.docx"),
                    func.lower(CandidateDocument.filename).like("%.doc"),
                ),
            )
            .order_by(
                CandidateDocument.is_primary.desc(),
                CandidateDocument.uploaded_at.desc(),
            )
            .limit(1)
        )
    ).first()

    if doc is not None:
        if doc.storage_key:
            try:
                content = await run_in_threadpool(
                    object_storage.download_cv, doc.storage_key
                )
                return CurrentCV(
                    content=content,
                    filename=doc.filename,
                    language=candidate.cv_language,
                    source="document_storage",
                )
            except Exception:  # noqa: BLE001 — fall through to other sources
                logger.exception(
                    "get_current_cv: object storage download failed "
                    "(candidate=%s, key=%s)",
                    candidate.id,
                    doc.storage_key,
                )
        if doc.file_content:
            return CurrentCV(
                content=bytes(doc.file_content),
                filename=doc.filename,
                language=candidate.cv_language,
                source="document_bytea",
            )

    if candidate.cv_storage_key:
        try:
            content = await run_in_threadpool(
                object_storage.download_cv, candidate.cv_storage_key
            )
            return CurrentCV(
                content=content,
                filename=candidate.cv_filename or "cv.pdf",
                language=candidate.cv_language,
                source="candidate_storage",
            )
        except Exception:  # noqa: BLE001
            logger.exception(
                "get_current_cv: candidate storage download failed "
                "(candidate=%s, key=%s)",
                candidate.id,
                candidate.cv_storage_key,
            )

    if candidate.cv_file_content is not None:
        return CurrentCV(
            content=bytes(candidate.cv_file_content),
            filename=candidate.cv_filename or "cv.pdf",
            language=candidate.cv_language,
            source="candidate_bytea",
        )

    return None
