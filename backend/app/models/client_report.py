"""Katalog raportów klienta: definicje raportów per klient i historia wysyłek.

CHECK-i i indeksy jak w ``app/services/client_reports_schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
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
from app.services import client_reports_schema as schema


class ClientReportDefinition(Base):
    __tablename__ = "client_report_definitions"
    __table_args__ = (
        CheckConstraint(schema.CK_FAMILY, name="ck_client_report_definitions_family"),
        CheckConstraint(schema.CK_RHYTHM, name="ck_client_report_definitions_rhythm"),
        CheckConstraint(
            schema.CK_PREPARER, name="ck_client_report_definitions_preparer"
        ),
        CheckConstraint(
            schema.CK_SOURCE_KIND, name="ck_client_report_definitions_source"
        ),
        CheckConstraint(
            schema.CK_DEFINITION_STATUS, name="ck_client_report_definitions_status"
        ),
        Index("ix_client_report_definitions_client", "client_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    family: Mapped[str] = mapped_column(String(12), nullable=False)
    generator_key: Mapped[Optional[str]] = mapped_column(
        String(schema.GENERATOR_MAX), nullable=True
    )
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    rhythm: Mapped[str] = mapped_column(String(16), nullable=False)
    due_rule: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
    )
    recipient: Mapped[Optional[str]] = mapped_column(
        String(schema.RECIPIENT_MAX), nullable=True
    )
    channel: Mapped[Optional[str]] = mapped_column(
        String(schema.CHANNEL_MAX), nullable=True
    )
    file_format: Mapped[Optional[str]] = mapped_column(
        String(schema.FORMAT_MAX), nullable=True
    )
    preparer: Mapped[str] = mapped_column(String(12), nullable=False)
    preparer_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source_kind: Mapped[str] = mapped_column(String(12), nullable=False)
    source_contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_framework_contracts.id", ondelete="SET NULL"),
        nullable=True,
    )
    source_chunk_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    source_ref: Mapped[Optional[str]] = mapped_column(
        String(schema.SOURCE_REF_MAX), nullable=True
    )
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ClientReportRun(Base):
    __tablename__ = "client_report_runs"
    __table_args__ = (
        CheckConstraint(schema.CK_RUN_STATUS, name="ck_client_report_runs_status"),
        CheckConstraint(schema.CK_SHA, name="ck_client_report_runs_sha"),
        CheckConstraint(schema.CK_SENT, name="ck_client_report_runs_sent"),
        Index("ix_client_report_runs_definition_period", "definition_id", "period_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    definition_id: Mapped[int] = mapped_column(
        ForeignKey("client_report_definitions.id", ondelete="CASCADE"),
        nullable=False,
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    period_key: Mapped[str] = mapped_column(
        String(schema.PERIOD_KEY_MAX), nullable=False
    )
    period_start: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_end: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX), nullable=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_PATH_MAX), nullable=True
    )
    content_type: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    generated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_to: Mapped[Optional[str]] = mapped_column(
        String(schema.SENT_TO_MAX), nullable=True
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
