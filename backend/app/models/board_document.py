"""Dokumenty Rady nadzorczej i odpisy KRS spółki (0727, R1).

CHECK-i i indeksy muszą być identyczne z ``app/services/board_documents_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
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
from app.services import board_documents_schema as schema


class BoardDocument(Base):
    """Dokument korporacyjny: plik od Zarządu albo wiersz z wzmianki KRS."""

    __tablename__ = "board_documents"
    __table_args__ = (
        CheckConstraint(schema.CK_CATEGORY, name="ck_board_documents_category"),
        CheckConstraint(schema.CK_ORGAN, name="ck_board_documents_organ"),
        CheckConstraint(schema.CK_SOURCE, name="ck_board_documents_source"),
        CheckConstraint(
            schema.CK_EXTRACTION_STATUS, name="ck_board_documents_extraction_status"
        ),
        CheckConstraint(schema.CK_EXTRACTION, name="ck_board_documents_extraction"),
        Index(
            "uq_board_documents_krs_key",
            "krs_key",
            unique=True,
            postgresql_where=text("krs_key IS NOT NULL"),
        ),
        Index(
            "ix_board_documents_category_date",
            "category",
            text("doc_date DESC NULLS LAST"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False)
    organ: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    number: Mapped[Optional[str]] = mapped_column(String(schema.NUMBER_MAX), nullable=True)
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX), nullable=False)
    subject: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    doc_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(
        String(8), nullable=False, default="upload", server_default="upload"
    )
    krs_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    krs_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    krs_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(schema.NAME_MAX), nullable=True)
    file_path: Mapped[Optional[str]] = mapped_column(String(schema.NAME_MAX), nullable=True)
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    extraction_status: Mapped[str] = mapped_column(
        String(8), nullable=False, default="none", server_default="none"
    )
    extraction: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BoardKrsSnapshot(Base):
    """Odpis pełny KRS spółki; nowy wiersz tylko przy zmianie treści."""

    __tablename__ = "board_krs_snapshots"
    __table_args__ = (
        CheckConstraint(schema.CK_PAYLOAD, name="ck_board_krs_snapshots_payload"),
        Index("uq_board_krs_snapshots_krs_sha", "krs", "sha256", unique=True),
        Index("ix_board_krs_snapshots_krs_fetched", "krs", text("fetched_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    krs: Mapped[str] = mapped_column(String(10), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entries_count: Mapped[int] = mapped_column(Integer, nullable=False)
    last_entry_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    last_entry_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
