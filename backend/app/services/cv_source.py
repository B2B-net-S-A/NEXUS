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

import hashlib
import logging
from dataclasses import dataclass

from fastapi.concurrency import run_in_threadpool
from sqlalchemy import ColumnElement, and_, case, func, not_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.models.candidate import Candidate
from app.models.candidate_document import CandidateDocument, CandidateDocumentKind
from app.services import object_storage
from app.services.candidate_identity_quarantine import (
    cv_bytes_quarantined,
    source_is_eligible_clause,
    source_is_quarantined_clause,
)
from app.services.client_cv_upload import CLIENT_CV_NAME
from app.core.log_safety import safe_storage_key

logger = logging.getLogger(__name__)


# Runda 9 (R9-N7-11): świadectwo albo list motywacyjny nie jest CV. Bez
# głównego CV brano najnowszy PDF DOWOLNEGO rodzaju, więc certyfikat wgrany
# po CV trafiał do migawki oryginału i do generatora. Dokumenty `other`
# zostają (import Traffita nie klasyfikuje plików), ale ustępują `cv`.
_NOT_CV_KINDS = (CandidateDocumentKind.certificate, CandidateDocumentKind.cover_letter)


def current_cv_filters() -> tuple:
    """Warunki „ten dokument może być bieżącym CV" (bez filtra rozszerzeń).

    Plik usunięty z profilu (`source_deleted_at`, 0435) nie jest niczyim CV.

    Audyt 48 h (13.10.2026):
    * plik z kwarantanny tożsamości (CV innej osoby, bez zwolnienia przez
      admina/HoR) też nie. Kwarantanna zdejmuje z pliku tylko `is_primary`,
      więc jako najnowszy wracał do każdej następnej kopii CV etapu;
    * „nieaktualne” (0400) nie może zostać głównym CV, więc nie jest też
      bieżącym — po usunięciu głównego CV z profilu nie wraca jako następca
      (`usun-plik-z-profilu-kandydata.md`). Plików „…B2B…” nie odsiewamy po
      nazwie: pomiar 02.11.2026 to 1280 osób, dla których firmowy Word jest
      jedynym CV. Ustępują CV kandydata w `current_cv_ordering`.
    """
    return (
        CandidateDocument.document_kind.notin_(_NOT_CV_KINDS),
        CandidateDocument.source_deleted_at.is_(None),
        CandidateDocument.outdated_at.is_(None),
        source_is_eligible_clause(
            candidate_id_column=CandidateDocument.candidate_id,
            source_id_column=CandidateDocument.id,
            source_kind="document",
        ),
    )


async def _legacy_cv_quarantined(db: AsyncSession, candidate_id: int) -> bool:
    """Czy CV ze wskaźnika kandydata (`legacy_cv`) jest w kwarantannie tożsamości."""
    return bool(
        await db.scalar(
            select(
                source_is_quarantined_clause(
                    candidate_id_column=candidate_id,
                    source_id_column=candidate_id,
                    source_kind="legacy_cv",
                )
            )
        )
    )


async def _pointer_copy_quarantined(
    db: AsyncSession, candidate_id: int, content: bytes
) -> bool:
    """Czy CV ze wskaźnika kandydata to kopia pliku z kwarantanny tożsamości."""
    return await cv_bytes_quarantined(
        db,
        candidate_id=candidate_id,
        content_sha256=hashlib.sha256(content).hexdigest(),
    )


def client_cv_file_clause() -> ColumnElement[bool]:
    """Firmowe CV po nazwie: Word „…B2B…” (lustro `looks_like_client_cv` bez wzoru klienta)."""
    return and_(
        CandidateDocument.filename.op("~*")(CLIENT_CV_NAME.pattern),
        func.lower(CandidateDocument.filename).like("%.docx"),
    )


def current_cv_ordering() -> tuple:
    """Kolejność wyboru bieżącego CV: główne → rodzaj „cv" → najnowsze.

    02.11.2026: firmowe CV (Word „…B2B…”) ustępuje CV kandydata rodzaju „cv”,
    także jako główne. Czytane jak oryginał przenosi swoje błędy i skróty do
    następnej generacji i do kopii „Oryginał CV”, z którą porównuje QC. „Other”
    go nie zastępuje: import Traffita nie klasyfikuje plików, a co piąty taki
    plik Word obok firmowego CV sam ma układ szablonu
    (`generator-cv/firmowe-cv-ustepuje-cv-kandydata.md`).

    04.11.2026: plik bez daty (import Traffita) idzie na koniec swojej rangi, bo
    Postgres przy DESC stawia NULL pierwszy i wygrywał z plikiem wgranym w NEXUSIE.
    Id kończy kolejność: bez niego wybór zależał od układu wierszy i sam UPDATE
    innej kolumny podmieniał plik w paczce CV.
    """
    is_cv = CandidateDocument.document_kind == CandidateDocumentKind.cv
    is_candidate_file = not_(client_cv_file_clause())
    return (
        case(
            (and_(CandidateDocument.is_primary, is_candidate_file), 0),
            (and_(is_cv, is_candidate_file), 1),
            (CandidateDocument.is_primary, 2),
            (is_cv, 3),
            else_=4,
        ),
        CandidateDocument.uploaded_at.desc().nulls_last(),
        CandidateDocument.id.desc(),
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

    # Wskaźnik CV na kandydacie uznany za CV innej osoby (kwarantanna
    # `legacy_cv`) nie jest bieżącym CV — jak plik z listy (audyt 13.10.2026).
    has_pointer = (
        bool(candidate.cv_storage_key) or candidate.cv_file_content is not None
    )
    if has_pointer and await _legacy_cv_quarantined(db, candidate.id):
        return None

    if candidate.cv_storage_key:
        content = None
        try:
            content = await run_in_threadpool(
                object_storage.download_cv, candidate.cv_storage_key
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "get_current_cv: candidate storage download failed "
                "(candidate=%s, key=%s): %s",
                candidate.id,
                safe_storage_key(candidate.cv_storage_key),
                type(exc).__name__,
            )
        if content is not None:
            # Wskaźnik trzyma własną kopię pliku, więc filtr dokumentów wyżej jej
            # nie widzi: 36 profili (05.11.2026) dostawało tu cudze CV.
            if await _pointer_copy_quarantined(db, candidate.id, content):
                return None
            return CurrentCV(
                content=content,
                filename=candidate.cv_filename or "cv.pdf",
                language=candidate.cv_language,
                source="candidate_storage",
            )

    if candidate.cv_file_content is not None:
        if await _pointer_copy_quarantined(
            db, candidate.id, bytes(candidate.cv_file_content)
        ):
            return None
        return CurrentCV(
            content=bytes(candidate.cv_file_content),
            filename=candidate.cv_filename or "cv.pdf",
            language=candidate.cv_language,
            source="candidate_bytea",
        )

    return None
