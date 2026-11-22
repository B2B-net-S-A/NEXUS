"""Kolejka odczytów CV wsadem (0750, Message Batches API).

CHECK i indeksy jak w ``app/services/cv_parse_batch_schema.py`` (strażnik dryfu
schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import cv_parse_batch_schema as schema


class CvParseBatchItem(Base):
    """Jedno główne CV z integracji czekające na odczyt w paczce."""

    __tablename__ = "cv_parse_batch_items"
    __table_args__ = (
        CheckConstraint(schema.CK_STATUS, name="ck_cv_parse_batch_items_status"),
        Index(
            "ix_cv_parse_batch_items_open",
            "status",
            "queued_at",
            postgresql_where=text(schema.OPEN_WHERE),
        ),
        Index("ix_cv_parse_batch_items_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_documents.id", ondelete="CASCADE"), nullable=False
    )
    content_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    trigger: Mapped[str] = mapped_column(
        String(40), nullable=False, default="cv_upload", server_default="cv_upload"
    )
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    #: ``ReplacedPrimaryCv`` z chwili wgrania: ``{"document_id", "cv_filename"}``.
    replaced_primary: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    #: Tekst pliku do zebrania wyniku; czyszczony po zamknięciu wiersza.
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="queued", server_default="queued"
    )
    batch_id: Mapped[Optional[str]] = mapped_column(String(80))
    model: Mapped[Optional[str]] = mapped_column(String(80))
    error: Mapped[Optional[str]] = mapped_column(String(255))
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    submitted_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
