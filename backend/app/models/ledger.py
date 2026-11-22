"""Księga NEXUSA (K1, 0700): lata, okresy, dokumenty z dekretem, dziennik, ślad.

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
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
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
from app.services import ledger_automation_schema as automation
from app.services import ledger_bank_balance_schema as bank_balances
from app.services import ledger_bank_schema as bank
from app.services import ledger_export_schema as export
from app.services import ledger_fx_schema as fx
from app.services import ledger_schema as schema
from app.services import ledger_settlement_schema as settlement
from app.services import ledger_vat_schema as vat_files


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
    #: Kurs pozycji, gdy inny niż kurs dokumentu (K4c-1, 0707 — WB walutowy).
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    fx_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


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


class LedgerRecurring(Base):
    """Wzór PK cyklicznego (K3a, 0701)."""

    __tablename__ = "ledger_recurring"
    __table_args__ = (
        CheckConstraint(
            automation.CK_RECURRING_MONTHS, name="ck_ledger_recurring_months"
        ),
        CheckConstraint(
            automation.CK_RECURRING_FIRST, name="ck_ledger_recurring_first"
        ),
        CheckConstraint(
            automation.CK_RECURRING_LINES, name="ck_ledger_recurring_lines"
        ),
        Index("ix_ledger_recurring_active", "active", "start_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(automation.NAME_MAX), nullable=False)
    description: Mapped[str] = mapped_column(
        String(schema.DESCRIPTION_MAX), nullable=False, default="", server_default=""
    )
    lines: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    end_month: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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


class LedgerPrepayment(Base):
    """RMK czynne — koszt rozliczany ratami miesięcznymi (K3a, 0701)."""

    __tablename__ = "ledger_prepayments"
    __table_args__ = (
        CheckConstraint(
            automation.CK_PREPAYMENT_AMOUNT, name="ck_ledger_prepayments_amount"
        ),
        CheckConstraint(
            automation.CK_PREPAYMENT_MONTHS, name="ck_ledger_prepayments_months"
        ),
        CheckConstraint(
            automation.CK_PREPAYMENT_FIRST, name="ck_ledger_prepayments_first"
        ),
        Index("ix_ledger_prepayments_active", "active", "start_month"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(automation.NAME_MAX), nullable=False)
    reference: Mapped[str] = mapped_column(
        String(automation.REFERENCE_MAX), nullable=False, default="", server_default=""
    )
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="SET NULL"), nullable=True
    )
    cost_account: Mapped[str] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=False
    )
    prepaid_account: Mapped[str] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=False
    )
    mpk: Mapped[Optional[str]] = mapped_column(String(schema.MPK_MAX), nullable=True)
    total_amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    start_month: Mapped[date] = mapped_column(Date, nullable=False)
    months: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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


class LedgerExport(Base):
    """Paczka księgi do Symfonii FK (K3b, 0702)."""

    __tablename__ = "ledger_exports"
    __table_args__ = (
        UniqueConstraint("number", name="uq_ledger_exports_number"),
        CheckConstraint(export.CK_EXPORT_STATUS, name="ck_ledger_exports_status"),
        CheckConstraint(export.CK_EXPORT_KINDS, name="ck_ledger_exports_kinds"),
        CheckConstraint(export.CK_EXPORT_COUNT, name="ck_ledger_exports_count"),
        Index("ix_ledger_exports_period", "period_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    year_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_years.id", ondelete="RESTRICT"), nullable=False
    )
    period_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_periods.id", ondelete="RESTRICT"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(export.NUMBER_MAX), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'exported'")
    )
    kinds: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    file_format: Mapped[str] = mapped_column(String(export.FORMAT_MAX), nullable=False)
    file_name: Mapped[str] = mapped_column(String(export.FILE_NAME_MAX), nullable=False)
    file_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    document_count: Mapped[int] = mapped_column(Integer, nullable=False)
    debit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    has_payroll: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    booked_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    booked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LedgerExportDocument(Base):
    """Dokument w paczce — najwyżej jedna aktywna paczka na dokument (K3b)."""

    __tablename__ = "ledger_export_documents"
    __table_args__ = (
        Index(
            "uq_ledger_export_documents_active",
            "document_id",
            unique=True,
            postgresql_where=text(export.EXPORT_ITEM_ACTIVE_WHERE),
        ),
    )

    export_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_exports.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_documents.id", ondelete="RESTRICT"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )


class LedgerBankStatement(Base):
    """Wyciąg bankowy wgrany w Księdze (K4a, 0705; salda i numery — 0742)."""

    __tablename__ = "ledger_bank_statements"
    __table_args__ = (
        UniqueConstraint("sha256", name="uq_ledger_bank_statements_sha"),
        CheckConstraint(
            bank.CK_STATEMENT_CURRENCY, name="ck_ledger_bank_statements_currency"
        ),
        CheckConstraint(
            bank_balances.CK_BALANCES, name="ck_ledger_bank_statements_balances"
        ),
        Index("ix_ledger_bank_statements_account", "bank_account", "last_day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    bank_account: Mapped[str] = mapped_column(String(26), nullable=False)
    ledger_account: Mapped[str] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=False
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'PLN'")
    )
    first_day: Mapped[date] = mapped_column(Date, nullable=False)
    last_day: Mapped[date] = mapped_column(Date, nullable=False)
    line_count: Mapped[int] = mapped_column(Integer, nullable=False)
    debit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    #: Saldo otwarcia i zamknięcia pliku (grosze ze znakiem) z datami sald —
    #: puste, gdy plik ich nie dowodzi (``ledger/bank_continuity.file_span``).
    opening_balance: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    opening_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closing_balance: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    closing_day: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Numer wyciągu banku pierwszej i ostatniej części pliku (``:28C:``).
    first_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    last_number: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    #: Uznania pliku przeszły przez E8 przy imporcie (faktury do klientów).
    credits_matched: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class LedgerBankLine(Base):
    """Operacja wyciągu z rozpoznaniem i kontem przeciwstawnym (K4a, 0705)."""

    __tablename__ = "ledger_bank_lines"
    __table_args__ = (
        UniqueConstraint("statement_id", "line_ref", name="uq_ledger_bank_lines_ref"),
        CheckConstraint(bank.CK_LINE_DIRECTION, name="ck_ledger_bank_lines_direction"),
        CheckConstraint(bank.CK_LINE_KIND, name="ck_ledger_bank_lines_kind"),
        CheckConstraint(bank.CK_LINE_AMOUNT, name="ck_ledger_bank_lines_amount"),
        CheckConstraint(fx.CK_BANK_LINE_CURRENCY, name="ck_ledger_bank_lines_currency"),
        CheckConstraint(fx.CK_BANK_LINE_FX, name="ck_ledger_bank_lines_fx"),
        Index("ix_ledger_bank_lines_statement", "statement_id", "position"),
        Index("ix_ledger_bank_lines_bank_ref", "bank_ref", "booked_on", "amount"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    statement_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_bank_statements.id", ondelete="CASCADE"), nullable=False
    )
    line_ref: Mapped[str] = mapped_column(String(bank.LINE_REF_MAX), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    bank_ref: Mapped[str] = mapped_column(
        String(bank.BANK_REF_MAX), nullable=False, server_default=text("''")
    )
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    direction: Mapped[str] = mapped_column(String(6), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    title: Mapped[str] = mapped_column(
        String(bank.TITLE_MAX), nullable=False, server_default=text("''")
    )
    counterparty_name: Mapped[str] = mapped_column(
        String(bank.NAME_MAX), nullable=False, server_default=text("''")
    )
    counterparty_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    ref_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    counter_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="SET NULL"), nullable=True
    )
    payroll: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    note: Mapped[str] = mapped_column(
        String(bank.NOTE_MAX), nullable=False, server_default=text("''")
    )
    assigned_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: K4c-1 (0707): ``amount`` jest w walucie wyciągu; operacja walutowa ma też
    #: kwotę w PLN po kursie NBP z ostatniego dnia roboczego przed operacją.
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default=text("'PLN'")
    )
    amount_pln: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    fx_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)


class LedgerSettlement(Base):
    """Rozliczenie zapisu Wn z zapisem Ma konta kontrahenta (K4b, 0706)."""

    __tablename__ = "ledger_settlements"
    __table_args__ = (
        CheckConstraint(settlement.CK_AMOUNT, name="ck_ledger_settlements_amount"),
        CheckConstraint(settlement.CK_METHOD, name="ck_ledger_settlements_method"),
        CheckConstraint(settlement.CK_LINES, name="ck_ledger_settlements_lines"),
        CheckConstraint(
            settlement.CK_SENSITIVITY, name="ck_ledger_settlements_sensitivity"
        ),
        CheckConstraint(
            fx.CK_SETTLEMENT_CURRENCY, name="ck_ledger_settlements_currency"
        ),
        Index(
            "ix_ledger_settlements_debit",
            "debit_line_id",
            postgresql_where=text(settlement.ACTIVE_WHERE),
        ),
        Index(
            "ix_ledger_settlements_credit",
            "credit_line_id",
            postgresql_where=text(settlement.ACTIVE_WHERE),
        ),
        Index(
            "ix_ledger_settlements_account",
            "account",
            "settled_on",
            postgresql_where=text(settlement.ACTIVE_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    account: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    debit_line_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_lines.id", ondelete="CASCADE"), nullable=False
    )
    credit_line_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_lines.id", ondelete="CASCADE"), nullable=False
    )
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    settled_on: Mapped[date] = mapped_column(Date, nullable=False)
    method: Mapped[str] = mapped_column(String(12), nullable=False)
    sensitivity: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    removed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    removed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: K4c-1 (0707): para pozycji w tej samej walucie obcej rozlicza się w walucie;
    #: ``amount`` = udział PLN pozycji Wn, ``credit_amount`` = udział PLN pozycji Ma.
    currency: Mapped[Optional[str]] = mapped_column(String(3), nullable=True)
    amount_cur: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    credit_amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)


class LedgerVatFile(Base):
    """Plik JPK_V7M za miesiąc — ewidencja VAT z deklaracją (K5b, 0708)."""

    __tablename__ = "ledger_vat_files"
    __table_args__ = (
        UniqueConstraint(
            "year", "month", "version", name="uq_ledger_vat_files_version"
        ),
        CheckConstraint(vat_files.CK_PERIOD, name="ck_ledger_vat_files_period"),
        CheckConstraint(vat_files.CK_PURPOSE, name="ck_ledger_vat_files_purpose"),
        CheckConstraint(vat_files.CK_STATUS, name="ck_ledger_vat_files_status"),
        CheckConstraint(vat_files.CK_REASON, name="ck_ledger_vat_files_reason"),
        CheckConstraint(vat_files.CK_SENT, name="ck_ledger_vat_files_sent"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    version: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    purpose: Mapped[str] = mapped_column(String(12), nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(
        String(vat_files.REASON_MAX), nullable=True
    )
    content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    totals: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'prepared'")
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_note: Mapped[Optional[str]] = mapped_column(
        String(vat_files.NOTE_MAX), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
