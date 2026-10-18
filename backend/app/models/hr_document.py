"""„Ludzie w NEXUSIE” — model: dokumenty osoby (e-teczka, 0468).

CHECK-i i indeksy muszą być identyczne z ``app/services/hr_documents_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis tabeli,
źródeł, kręgu widzących i retencji — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_documents_schema as schema


class HrDocument(Base, TimestampMixin):
    """Dokument przy osobie — widzą Kadry, admin i krąg ze znaczników."""

    __tablename__ = "hr_documents"
    __table_args__ = (
        CheckConstraint(schema.CK_DOCUMENT_KIND, name="ck_hr_documents_kind"),
        CheckConstraint(schema.CK_DOCUMENT_PURPOSE, name="ck_hr_documents_purpose"),
        CheckConstraint(schema.CK_DOCUMENT_SOURCE, name="ck_hr_documents_source"),
        CheckConstraint(
            schema.CK_DOCUMENT_SOURCE_REF, name="ck_hr_documents_source_ref"
        ),
        CheckConstraint(schema.CK_DOCUMENT_TITLE, name="ck_hr_documents_title"),
        CheckConstraint(schema.CK_DOCUMENT_MIME, name="ck_hr_documents_mime"),
        CheckConstraint(schema.CK_DOCUMENT_SIZE, name="ck_hr_documents_size"),
        CheckConstraint(schema.CK_DOCUMENT_SHA, name="ck_hr_documents_sha"),
        CheckConstraint(schema.CK_DOCUMENT_FILE, name="ck_hr_documents_file"),
        CheckConstraint(schema.CK_DOCUMENT_DELETED, name="ck_hr_documents_deleted"),
        CheckConstraint(
            schema.CK_DOCUMENT_DELETION_NOTE, name="ck_hr_documents_deletion_note"
        ),
        Index("ix_hr_documents_user", "user_id"),
        Index(
            "uq_hr_documents_source_ref",
            "source",
            "source_ref",
            unique=True,
            postgresql_where=text(schema.SOURCE_REF_WHERE),
        ),
        Index(
            "uq_hr_documents_live_upload",
            "user_id",
            "sha256",
            unique=True,
            postgresql_where=text(schema.LIVE_UPLOAD_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    #: ``student_status`` — oświadczenie ucznia/studenta (zasila kartotekę).
    purpose: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX_LENGTH), nullable=False)
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="upload", server_default="upload"
    )
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(schema.SOURCE_REF_MAX_LENGTH), nullable=True
    )
    #: Ścieżka względna pod ``storage_service.STORAGE_ROOT`` (NULL po usunięciu).
    file_path: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX_LENGTH), nullable=True
    )
    mime: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    valid_until: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    visible_to_person: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    visible_to_payroll: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    visible_to_equipment: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    deleted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    deletion_reason: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    deletion_note: Mapped[Optional[str]] = mapped_column(
        String(schema.NOTE_MAX_LENGTH), nullable=True
    )
