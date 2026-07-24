"""Multi-file documents per kandydat (Faza A migracji Traffit→Nexus).

W przeciwieństwie do `candidates.cv_file_content` (single primary CV) i
`candidate_stage_cvs.original_cv_content` (per-rekrutacja snapshot),
`candidate_documents` przechowuje **wszystkie** pliki przypisane do
kandydata: różne wersje CV, listy motywacyjne, certyfikaty.

Pole `is_primary` zaznacza preferowany plik do wyświetlenia jako pierwszy
(zachowuje priorytet `pdf > docx > doc` z `select_primary_cv_file`).

Idempotentność migracji z Traffita: `external_source='traffit'` +
`external_id='{traffit_employee_id}-{file_id}'` z partial unique index.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    Enum,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    text,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateDocumentKind(str, enum.Enum):
    """Business type of a candidate attachment.

    Only ``cv`` documents participate in the CV gallery. Generic Traffit
    attachments remain ``other`` until a recruiter classifies them.
    """

    cv = "cv"
    cover_letter = "cover_letter"
    certificate = "certificate"
    other = "other"


class CandidateDocument(Base, TimestampMixin):
    __tablename__ = "candidate_documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    filename: Mapped[str] = mapped_column(String(500), nullable=False)
    # Lazy-loaded — nie pobieraj BYTEA przy SELECT * (kilkadziesiąt MB per row).
    # Po migracji do Hetzner Object Storage (audit-2026-05-07, migracja 0079)
    # file_content jest NULL dla rekordów ze ``storage_key`` set; nowy upload
    # idzie bezpośrednio do object storage. Zostawiamy nullable=True jako
    # tymczasowy fallback dla legacy rows do czasu finalize-delete-bytea.
    file_content: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    # Klucz w Hetzner Object Storage (np. 'cv/2026/05/abc123-cv.pdf').
    # NULL = legacy row z file_content w postgres BYTEA (przed migracją).
    storage_key: Mapped[Optional[str]] = mapped_column(
        String(500), nullable=True, index=True
    )
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    document_kind: Mapped[CandidateDocumentKind] = mapped_column(
        Enum(CandidateDocumentKind, name="candidatedocumentkind"),
        default=CandidateDocumentKind.other,
        server_default=CandidateDocumentKind.other.value,
        nullable=False,
        index=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Idempotency: external_source='traffit', external_id='<emp_id>-<file_id>'
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", nullable=True
    )
    # Tożsamość treści + stan manifestu źródła (idempotentna, wersjonowana
    # synchronizacja plików — plik o tym samym SHA nie jest wysyłany ponownie).
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source_manifest_fingerprint: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    source_deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="documents")

    __table_args__ = (
        Index(
            "ux_candidate_documents_candidate_sha",
            "candidate_id",
            "content_sha256",
            unique=True,
            postgresql_where=text(
                "content_sha256 IS NOT NULL AND source_deleted_at IS NULL"
            ),
        ),
        Index(
            "ix_candidate_documents_manifest",
            "candidate_id",
            "source_manifest_fingerprint",
        ),
        Index(
            "ux_candidate_documents_active_primary_cv",
            "candidate_id",
            unique=True,
            postgresql_where=text(
                "is_primary IS TRUE "
                "AND source_deleted_at IS NULL "
                "AND document_kind = 'cv'"
            ),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateDocument id={self.id} candidate={self.candidate_id} "
            f"filename={self.filename!r} primary={self.is_primary}>"
        )
