"""Rozliczenia Nordei N1: kartoteka identyfikatorów u klienta i wersje raportu T4T.

CHECK-i i indeksy jak w ``app/services/client_time_reports_schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import client_time_reports_schema as schema


class ClientExternalId(Base):
    __tablename__ = "client_external_ids"
    __table_args__ = (
        UniqueConstraint(
            "client_id",
            "contract_id",
            "kind",
            "value",
            name="uq_client_external_ids_value",
        ),
        CheckConstraint(schema.CK_ID_KIND, name="ck_client_external_ids_kind"),
        CheckConstraint(schema.CK_ID_SOURCE, name="ck_client_external_ids_source"),
        CheckConstraint(schema.CK_ID_STATE, name="ck_client_external_ids_state"),
        Index("ix_client_external_ids_lookup", "client_id", "kind", "value"),
        Index("ix_client_external_ids_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    value: Mapped[str] = mapped_column(String(schema.ID_VALUE_MAX), nullable=False)
    valid_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    valid_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    source: Mapped[str] = mapped_column(String(12), nullable=False)
    state: Mapped[str] = mapped_column(String(10), nullable=False)
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


class ClientTimeReport(Base):
    __tablename__ = "client_time_reports"
    __table_args__ = (
        UniqueConstraint("client_id", "sha256", name="uq_client_time_reports_sha"),
        UniqueConstraint(
            "client_id",
            "period_month",
            "version_no",
            name="uq_client_time_reports_version",
        ),
        CheckConstraint(schema.PERIOD_CHECK, name="ck_client_time_reports_period"),
        CheckConstraint(schema.CK_SHA, name="ck_client_time_reports_sha"),
        CheckConstraint(schema.CK_VERSION, name="ck_client_time_reports_version"),
        Index("ix_client_time_reports_month", "client_id", "period_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    received_on: Mapped[date] = mapped_column(Date, nullable=False)
    file_name: Mapped[Optional[str]] = mapped_column(
        String(schema.FILE_NAME_MAX), nullable=True
    )
    sheet_name: Mapped[Optional[str]] = mapped_column(
        String(schema.SHEET_NAME_MAX), nullable=True
    )
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    rows_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    people_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0", default=0
    )
    hours_approved: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0", default=Decimal("0")
    )
    hours_submitted: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, server_default="0", default=Decimal("0")
    )
    uploaded_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientTimeReportRow(Base):
    __tablename__ = "client_time_report_rows"
    __table_args__ = (
        Index("ix_client_time_report_rows_report_person", "report_id", "person_no"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_id: Mapped[int] = mapped_column(
        ForeignKey("client_time_reports.id", ondelete="CASCADE"), nullable=False
    )
    person_no: Mapped[str] = mapped_column(String(schema.ID_VALUE_MAX), nullable=False)
    person_name: Mapped[Optional[str]] = mapped_column(
        String(schema.PERSON_NAME_MAX), nullable=True
    )
    project_no: Mapped[Optional[str]] = mapped_column(
        String(schema.ID_VALUE_MAX), nullable=True
    )
    project_name: Mapped[Optional[str]] = mapped_column(
        String(schema.PROJECT_NAME_MAX), nullable=True
    )
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    work_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    hours: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    status: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    charge_code: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    company: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
