"""Przelewy i zapłaty faktur kosztowych (0697, E3).

CHECK-i i indeksy muszą być identyczne z ``app/services/finance_payments_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Opis tabel — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
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
from app.services import finance_payments_schema as schema


class FinanceCostPayment(Base):
    __tablename__ = "finance_cost_payments"
    __table_args__ = (
        CheckConstraint(schema.CK_PAYMENT_STATE, name="ck_finance_cost_payments_state"),
        CheckConstraint(schema.CK_PAID_SOURCE, name="ck_finance_cost_payments_source"),
        CheckConstraint(schema.CK_PAID_AMOUNT, name="ck_finance_cost_payments_amount"),
        Index("ix_finance_cost_payments_state", "state"),
    )

    entry_id: Mapped[int] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="CASCADE"), primary_key=True
    )
    state: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unpaid", server_default="unpaid"
    )
    account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    paid_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    paid_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    paid_source: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    account_changed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    account_changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
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


class FinanceCounterpartyAccount(Base):
    __tablename__ = "finance_counterparty_accounts"

    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="CASCADE"), primary_key=True
    )
    account: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class FinancePaymentBatch(Base):
    __tablename__ = "finance_payment_batches"
    __table_args__ = (
        CheckConstraint(
            schema.CK_BATCH_FORMAT, name="ck_finance_payment_batches_format"
        ),
        CheckConstraint(
            schema.CK_BATCH_STATUS, name="ck_finance_payment_batches_status"
        ),
        CheckConstraint(
            schema.CK_BATCH_ELIXIR_PLN, name="ck_finance_payment_batches_elixir_pln"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    format: Mapped[str] = mapped_column(String(8), nullable=False)
    execution_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="active", server_default="active"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Ostatnia zmiana składu paczki („Zdejmij z paczki”) i ostatnie pobranie
    #: pliku ze skrótem — plik pobrany przed zmianą jest nieaktualny.
    changed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    downloaded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    file_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)


class FinancePaymentBatchItem(Base):
    __tablename__ = "finance_payment_batch_items"
    __table_args__ = (
        CheckConstraint(
            schema.CK_ITEM_STATUS, name="ck_finance_payment_batch_items_status"
        ),
        CheckConstraint(
            schema.CK_ITEM_MODE, name="ck_finance_payment_batch_items_mode"
        ),
        CheckConstraint(
            schema.CK_ITEM_AMOUNT, name="ck_finance_payment_batch_items_amount"
        ),
        CheckConstraint(
            schema.CK_ITEM_ACCOUNT_SOURCE,
            name="ck_finance_payment_batch_items_account_source",
        ),
        Index(
            "uq_finance_payment_batch_items_active",
            "entry_id",
            unique=True,
            postgresql_where=text(schema.ACTIVE_ITEM_WHERE),
        ),
        Index("ix_finance_payment_batch_items_batch", "batch_id", "id"),
        Index("ix_finance_payment_batch_items_entry", "entry_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    batch_id: Mapped[int] = mapped_column(
        ForeignKey("finance_payment_batches.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="active", server_default="active"
    )
    mode: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    account: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    account_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    recipient_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    title_lines: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    white_list: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    acknowledged_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class FinanceCostPaymentRecord(Base):
    __tablename__ = "finance_cost_payment_records"
    __table_args__ = (
        CheckConstraint(
            schema.CK_RECORD_KIND, name="ck_finance_cost_payment_records_kind"
        ),
        CheckConstraint(
            schema.CK_RECORD_STATUS, name="ck_finance_cost_payment_records_status"
        ),
        CheckConstraint(
            schema.CK_RECORD_MATCHED, name="ck_finance_cost_payment_records_matched"
        ),
        CheckConstraint(
            schema.CK_RECORD_STATEMENT,
            name="ck_finance_cost_payment_records_statement",
        ),
        Index(
            "uq_finance_cost_payment_records_statement",
            "statement_sha256",
            "statement_line_ref",
            unique=True,
            postgresql_where=text(schema.STATEMENT_WHERE),
        ),
        Index("ix_finance_cost_payment_records_entry", "entry_id"),
        Index("ix_finance_cost_payment_records_status", "match_status", "booked_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="SET NULL"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(String(10), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    booked_on: Mapped[date] = mapped_column(Date, nullable=False)
    title: Mapped[Optional[str]] = mapped_column(
        String(schema.TITLE_MAX), nullable=True
    )
    counterparty_name: Mapped[Optional[str]] = mapped_column(
        String(schema.NAME_MAX), nullable=True
    )
    counterparty_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX), nullable=True
    )
    candidates: Mapped[list[int]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    statement_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    statement_format: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    statement_line_ref: Mapped[Optional[str]] = mapped_column(
        String(schema.LINE_REF_MAX), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class FinanceCounterpartyAccountEvent(Base):
    """Historia rachunku kontrahenta w kartotece (stary → nowy, kto, kiedy)."""

    __tablename__ = "finance_counterparty_account_events"
    __table_args__ = (
        Index("ix_finance_counterparty_account_events_party", "counterparty_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    counterparty_id: Mapped[int] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="CASCADE"), nullable=False
    )
    entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="SET NULL"), nullable=True
    )
    old_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    new_account: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
