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

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
)
from sqlalchemy.orm import Mapped, deferred, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


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
    file_content: Mapped[Optional[bytes]] = deferred(
        mapped_column(LargeBinary, nullable=True)
    )
    content_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    uploaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Idempotency: external_source='traffit', external_id='<emp_id>-<file_id>'
    external_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    external_source: Mapped[Optional[str]] = mapped_column(
        String(50), default="manual", nullable=True
    )

    # Relationships
    candidate = relationship("Candidate", back_populates="documents")

    def __repr__(self) -> str:
        return (
            f"<CandidateDocument id={self.id} candidate={self.candidate_id} "
            f"filename={self.filename!r} primary={self.is_primary}>"
        )
