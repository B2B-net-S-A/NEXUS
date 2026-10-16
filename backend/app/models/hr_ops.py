"""Ślad HR, rezerwacje zadań okresowych i import z Compassa (migracja 0452).

* ``HrAuditEvent`` — zmiany w kartotece, urlopach i płacach z poziomem
  wrażliwości; odczyt filtruje wiersze po uprawnieniu czytającego
  (zdrowie: osoba, przełożony, Kadry; płace: Płace). ``critical_events``
  dostaje najwyżej zdanie bez kwot.
* ``HrJobRun`` — jeden przebieg zadania na okres (``kind`` + ``period_key``);
  nocny restart przy wdrożeniu nie powtarza wysyłki ani zamknięcia miesiąca.
* ``HrImportBatch`` / ``HrImportIdMap`` — paczki importu z Compassa i mapa
  identyfikatorów (raport niesie same liczby, bez nazwisk i kwot).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import hr_foundation_schema as schema


class HrAuditEvent(Base):
    __tablename__ = "hr_audit_events"
    __table_args__ = (
        CheckConstraint(schema.CK_SENSITIVITY, name="ck_hr_audit_events_sensitivity"),
        Index("ix_hr_audit_events_subject", "subject_user_id", "created_at"),
        Index("ix_hr_audit_events_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    subject_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    entity_type: Mapped[str] = mapped_column(String(40), nullable=False)
    entity_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(60), nullable=False)
    sensitivity: Mapped[str] = mapped_column(
        String(16), nullable=False, default="general", server_default="general"
    )
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class HrJobRun(Base):
    __tablename__ = "hr_job_runs"
    __table_args__ = (
        UniqueConstraint("kind", "period_key", name="uq_hr_job_runs_kind_period"),
        CheckConstraint(schema.CK_JOB_RUN_STATUS, name="ck_hr_job_runs_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(60), nullable=False)
    period_key: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="claimed", server_default="claimed"
    )
    counts: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    claimed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HrImportBatch(Base):
    __tablename__ = "hr_import_batches"
    __table_args__ = (
        CheckConstraint(schema.CK_IMPORT_MODULE, name="ck_hr_import_batches_module"),
        CheckConstraint(schema.CK_IMPORT_STATUS, name="ck_hr_import_batches_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    bundle_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    schema_version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="uploaded", server_default="uploaded"
    )
    report: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    applied_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HrImportIdMap(Base):
    __tablename__ = "hr_import_id_map"
    __table_args__ = (
        UniqueConstraint("module", "source_id", name="uq_hr_import_id_map_source"),
        CheckConstraint(schema.CK_IMPORT_DECISION, name="ck_hr_import_id_map_decision"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    module: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str] = mapped_column(String(64), nullable=False)
    target_table: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(64), nullable=False)
    decision: Mapped[str] = mapped_column(
        String(16), nullable=False, default="auto", server_default="auto"
    )
    batch_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hr_import_batches.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
