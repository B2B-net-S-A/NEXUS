"""Archiwum dokumentów z eBI24 (0720, E5).

CHECK-i i indeksy muszą być identyczne z ``app/services/finance_archive_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import finance_archive_schema as schema


class FinanceArchiveDocument(Base):
    """Dokument z archiwum eBI24: metadane w bazie, plik na dysku."""

    __tablename__ = "finance_archive_documents"
    __table_args__ = (
        CheckConstraint(
            schema.CK_ARCHIVE_KIND, name="ck_finance_archive_documents_kind"
        ),
        CheckConstraint(
            schema.CK_ARCHIVE_FILE_TYPE, name="ck_finance_archive_documents_file_type"
        ),
        CheckConstraint(
            schema.CK_ARCHIVE_META, name="ck_finance_archive_documents_meta"
        ),
        Index(
            "uq_finance_archive_documents_source", "source", "source_id", unique=True
        ),
        Index("ix_finance_archive_documents_date", text("issue_date DESC")),
        Index("ix_finance_archive_documents_partner", "partner_id"),
        Index("ix_finance_archive_documents_number", text("lower(invoice_number)")),
        Index(
            "ix_finance_archive_documents_ksef",
            "ksef_number",
            postgresql_where=text("ksef_number IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="ebi24", server_default="ebi24"
    )
    source_id: Mapped[str] = mapped_column(String(schema.SOURCE_ID_MAX), nullable=False)
    bucket_number: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    schema_name: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    invoice_number: Mapped[Optional[str]] = mapped_column(
        String(schema.NUMBER_MAX), nullable=True
    )
    title: Mapped[Optional[str]] = mapped_column(String(schema.TEXT_MAX), nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    document_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    partner_name: Mapped[Optional[str]] = mapped_column(
        String(schema.NAME_MAX), nullable=True
    )
    partner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    vat_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    gross_pln: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    paid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    ksef_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    folder: Mapped[Optional[str]] = mapped_column(
        String(schema.TEXT_MAX), nullable=True
    )
    file_type: Mapped[str] = mapped_column(String(8), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.TEXT_MAX), nullable=True
    )
    file_path: Mapped[str] = mapped_column(String(schema.TEXT_MAX), nullable=False)
    file_size: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    imported_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    imported_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
