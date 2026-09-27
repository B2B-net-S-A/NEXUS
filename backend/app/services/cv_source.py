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
from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services import object_storage
from app.core.log_safety import safe_storage_key

logger = logging.getLogger(__name__)


# Runda 9 (R9-N7-11): świadectwo albo list motywacyjny nie jest CV. Bez
# głównego CV brano najnowszy PDF DOWOLNEGO rodzaju, więc certyfikat wgrany
# po CV trafiał do migawki oryginału i do generatora. Dokumenty `other`
# zostają (import Traffita nie klasyfikuje plików), ale ustępują `cv`.
_NOT_CV_KINDS = (CandidateDocumentKind.certificate, CandidateDocumentKind.cover_letter)


def current_cv_filters() -> tuple:
    """Warunki „ten dokument może być bieżącym CV" (bez filtra rozszerzeń)."""
    return (CandidateDocument.document_kind.notin_(_NOT_CV_KINDS),)


def current_cv_ordering() -> tuple:
    """Kolejność wyboru bieżącego CV: główne → rodzaj „cv" → najnowsze."""
    return (
        CandidateDocument.is_primary.desc(),
        case(
            (CandidateDocument.document_kind == CandidateDocumentKind.cv, 0),
            else_=1,
        ),
        CandidateDocument.uploaded_at.desc(),
    )


@dataclass(frozen=True)
class CurrentCV:
    content: bytes
    filename: str
    language: str | None
    source: str  # 'document_storage' | 'document_bytea' | 'candidate_storage' | 'candidate_bytea'


async def get_current_cv(db: AsyncSession, candidate: Candidate) -> CurrentCV | None:
    """Resolve the candidate's current CV bytes, wherever they live.

    Priority: primary/most-recent ``CandidateDocument`` (object storage, then
    legacy BYTEA) → ``Candidate.cv_storage_key`` → legacy
    ``Candidate.cv_file_content``. Object-storage downloads run in a worker
    thread (boto3 is sync). Returns ``None`` when the candidate has no CV.
    """
    doc = (
        await db.scalars(
            select(CandidateDocument)
            # Runda 9 (R9-X1-1): `file_content` jest odroczone — odczyt bez
            # `undefer` w sesji async to MissingGreenlet (500 przy CV
            # z formularza kariery / maila, które leży w BYTEA bez storage_key).
            .options(undefer(CandidateDocument.file_content))
            .where(
                CandidateDocument.candidate_id == candidate.id,
                or_(
                    func.lower(CandidateDocument.filename).like("%.pdf"),
                    func.lower(CandidateDocument.filename).like("%.docx"),
                    func.lower(CandidateDocument.filename).like("%.doc"),
                ),
                *current_cv_filters(),
            )
            .order_by(*current_cv_ordering())
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
            except Exception as exc:  # noqa: BLE001 — fall through to other sources
                # Runda 9 (R9-N7-8): bez tracebacku — komunikat wyjątku boto3
                # powtarza URL z pełnym kluczem (nazwa pliku CV).
                logger.warning(
                    "get_current_cv: object storage download failed "
                    "(candidate=%s, key=%s): %s",
                    candidate.id,
                    safe_storage_key(doc.storage_key),
                    type(exc).__name__,
                )
        # `file_content` jest odroczone (`deferred`) — dostęp do atrybutu na
        # sesji async to MissingGreenlet, więc bajty czytamy jawnym zapytaniem
        # (runda 9: paczka CV czyta główny dokument przez tę funkcję).
        file_content = await db.scalar(
            select(CandidateDocument.file_content).where(CandidateDocument.id == doc.id)
        )
        if file_content:
            return CurrentCV(
                content=bytes(file_content),
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
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_current_cv: candidate storage download failed "
                "(candidate=%s, key=%s): %s",
                candidate.id,
                safe_storage_key(candidate.cv_storage_key),
                type(exc).__name__,
            )

    if candidate.cv_file_content is not None:
        return CurrentCV(
            content=bytes(candidate.cv_file_content),
            filename=candidate.cv_filename or "cv.pdf",
            language=candidate.cv_language,
            source="candidate_bytea",
        )

    return None
