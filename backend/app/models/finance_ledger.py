"""Księgowość w Finansach (0696, E0 i E1): kontrahenci i kolejka kosztów.

CHECK-i i indeksy muszą być identyczne z ``app/services/finance_ledger_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Opis tabel — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

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
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import finance_ledger_schema as schema


class FinanceCounterparty(Base):
    __tablename__ = "finance_counterparties"
    __table_args__ = (
        CheckConstraint(schema.CK_ID_TYPE, name="ck_finance_counterparties_id_type"),
        CheckConstraint(schema.CK_ID_PAIR, name="ck_finance_counterparties_id_pair"),
        CheckConstraint(schema.CK_KEY, name="ck_finance_counterparties_key"),
        Index(
            "uq_finance_counterparties_identifier",
            "id_type",
            "id_value",
            unique=True,
            postgresql_where=text(schema.IDENTIFIER_WHERE),
        ),
        Index(
            "uq_finance_counterparties_symfonia",
            "symfonia_partner_id",
            unique=True,
            postgresql_where=text(schema.SYMFONIA_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    id_type: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    id_value: Mapped[Optional[str]] = mapped_column(
        String(schema.ID_VALUE_MAX), nullable=True
    )
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    street: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    postal_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    city: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    country: Mapped[Optional[str]] = mapped_column(String(2), nullable=True)
    email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    symfonia_partner_id: Mapped[Optional[str]] = mapped_column(
        String(schema.SYMFONIA_ID_MAX), nullable=True
    )
    cost_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    revenue_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    imported_at: Mapped[Optional[datetime]] = mapped_column(
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


class FinanceCostEntry(Base):
    __tablename__ = "finance_cost_entries"
    __table_args__ = (
        UniqueConstraint(
            "source_type", "source_id", name="uq_finance_cost_entries_source"
        ),
        CheckConstraint(
            schema.CK_SOURCE_TYPE, name="ck_finance_cost_entries_source_type"
        ),
        CheckConstraint(schema.CK_STAGE, name="ck_finance_cost_entries_stage"),
        CheckConstraint(schema.CK_CATEGORY, name="ck_finance_cost_entries_category"),
        CheckConstraint(schema.CK_FLAGS, name="ck_finance_cost_entries_flags"),
        CheckConstraint(schema.CK_MPP, name="ck_finance_cost_entries_mpp"),
        CheckConstraint(schema.CK_REJECTED, name="ck_finance_cost_entries_rejected"),
        Index("ix_finance_cost_entries_stage", "stage", "received_at"),
        Index("ix_finance_cost_entries_seller", "seller_nip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    from_ksef: Mapped[bool] = mapped_column(Boolean, nullable=False)
    stage: Mapped[str] = mapped_column(String(10), nullable=False)
    flags: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )
    category: Mapped[str] = mapped_column(String(12), nullable=False)
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="SET NULL"), nullable=True
    )
    seller_nip: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    reject_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX), nullable=True
    )
    stage_changed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    stage_changed_at: Mapped[Optional[datetime]] = mapped_column(
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


class FinanceCostEntryEvent(Base):
    __tablename__ = "finance_cost_entry_events"
    __table_args__ = (
        CheckConstraint(
            schema.CK_EVENT_ACTION, name="ck_finance_cost_entry_events_action"
        ),
        Index("ix_finance_cost_entry_events_entry", "entry_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entry_id: Mapped[int] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="CASCADE"), nullable=False
    )
    action: Mapped[str] = mapped_column(String(12), nullable=False)
    from_stage: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    to_stage: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
