"""Księga NEXUSA (K1, 0699): lata, okresy, dokumenty z dekretem, dziennik, ślad.

CHECK-i i indeksy muszą być identyczne z ``app/services/ledger_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Opis tabel — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
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
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import ledger_schema as schema


class LedgerYear(Base):
    __tablename__ = "ledger_years"
    __table_args__ = (
        UniqueConstraint("year", name="uq_ledger_years_year"),
        CheckConstraint(schema.CK_YEAR_MODE, name="ck_ledger_years_mode"),
        CheckConstraint(schema.CK_YEAR_STATUS, name="ck_ledger_years_status"),
        CheckConstraint(schema.CK_YEAR_DATES, name="ck_ledger_years_dates"),
        CheckConstraint(schema.CK_YEAR_NEXT, name="ck_ledger_years_next"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    mode: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'symfonia'")
    )
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'open'")
    )
    next_journal_no: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("1")
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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


class LedgerPeriod(Base):
    __tablename__ = "ledger_periods"
    __table_args__ = (
        UniqueConstraint("year_id", "month", name="uq_ledger_periods_month"),
        CheckConstraint(schema.CK_PERIOD_MONTH, name="ck_ledger_periods_month"),
        CheckConstraint(schema.CK_PERIOD_STATUS, name="ck_ledger_periods_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_years.id", ondelete="CASCADE"), nullable=False
    )
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    starts_on: Mapped[date] = mapped_column(Date, nullable=False)
    ends_on: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default=text("'open'")
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reopened_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reopened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reopen_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerDocument(Base):
    __tablename__ = "ledger_documents"
    __table_args__ = (
        CheckConstraint(schema.CK_DOC_TYPE, name="ck_ledger_documents_type"),
        CheckConstraint(schema.CK_DOC_STATUS, name="ck_ledger_documents_status"),
        CheckConstraint(schema.CK_DOC_JOURNAL, name="ck_ledger_documents_journal"),
        CheckConstraint(schema.CK_DOC_BALANCE, name="ck_ledger_documents_balance"),
        CheckConstraint(
            schema.CK_DOC_SENSITIVITY, name="ck_ledger_documents_sensitivity"
        ),
        CheckConstraint(schema.CK_DOC_SOURCE, name="ck_ledger_documents_source"),
        CheckConstraint(schema.CK_DOC_FX, name="ck_ledger_documents_fx"),
        Index(
            "uq_ledger_documents_journal",
            "year_id",
            "journal_no",
            unique=True,
            postgresql_where=text(schema.DOC_JOURNAL_WHERE),
        ),
        Index(
            "uq_ledger_documents_source",
            "source_type",
            "source_id",
            unique=True,
            postgresql_where=text(schema.DOC_SOURCE_WHERE),
        ),
        Index("ix_ledger_documents_period", "period_id", "doc_type", "status"),
        Index(
            "ix_ledger_documents_counterparty",
            "counterparty_id",
            postgresql_where=text(schema.DOC_COUNTERPARTY_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_years.id", ondelete="RESTRICT"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_periods.id", ondelete="RESTRICT"), nullable=False
    )
    doc_type: Mapped[str] = mapped_column(String(4), nullable=False)
    number: Mapped[str] = mapped_column(String(schema.NUMBER_MAX), nullable=False)
    op_date: Mapped[date] = mapped_column(Date, nullable=False)
    doc_date: Mapped[date] = mapped_column(Date, nullable=False)
    description: Mapped[str] = mapped_column(
        String(schema.DESCRIPTION_MAX), nullable=False, server_default=text("''")
    )
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="RESTRICT"), nullable=True
    )
    source_type: Mapped[Optional[str]] = mapped_column(
        String(schema.SOURCE_TYPE_MAX), nullable=True
    )
    source_id: Mapped[Optional[str]] = mapped_column(
        String(schema.SOURCE_ID_MAX), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'PLN'")
    )
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 6), nullable=True)
    fx_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'draft'")
    )
    journal_no: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    debit_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    credit_total: Mapped[int] = mapped_column(
        BigInteger, nullable=False, server_default=text("0")
    )
    sensitivity: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    reverses_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ledger_documents.id", ondelete="RESTRICT"), nullable=True
    )
    reversed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ledger_documents.id", ondelete="SET NULL"), nullable=True
    )
    meta: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
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
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LedgerLine(Base):
    __tablename__ = "ledger_lines"
    __table_args__ = (
        UniqueConstraint("document_id", "line_no", name="uq_ledger_lines_no"),
        CheckConstraint(schema.CK_LINE_SIDE, name="ck_ledger_lines_side"),
        CheckConstraint(schema.CK_LINE_AMOUNT, name="ck_ledger_lines_amount"),
        Index("ix_ledger_lines_account", "account", "document_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_documents.id", ondelete="CASCADE"), nullable=False
    )
    line_no: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    side: Mapped[str] = mapped_column(String(6), nullable=False)
    account: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'PLN'")
    )
    amount_cur: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="RESTRICT"), nullable=True
    )
    mpk: Mapped[Optional[str]] = mapped_column(String(schema.MPK_MAX), nullable=True)
    description: Mapped[str] = mapped_column(
        String(schema.LINE_TEXT_MAX), nullable=False, server_default=text("''")
    )


class LedgerEvent(Base):
    __tablename__ = "ledger_events"
    __table_args__ = (
        CheckConstraint(schema.CK_EVENT_ACTION, name="ck_ledger_events_action"),
        Index("ix_ledger_events_document", "document_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ledger_documents.id", ondelete="SET NULL"), nullable=True
    )
    period_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("ledger_periods.id", ondelete="SET NULL"), nullable=True
    )
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
