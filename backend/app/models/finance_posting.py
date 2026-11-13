"""Księgowość w Finansach (0697, E2): plan kont, reguły dekretu, paczki eksportu.

CHECK-i i indeksy muszą być identyczne z ``app/services/finance_posting_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Opis tabel — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

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
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import finance_posting_schema as schema


class FinanceAccount(Base):
    __tablename__ = "finance_accounts"
    __table_args__ = (
        UniqueConstraint("number", name="uq_finance_accounts_number"),
        CheckConstraint(schema.CK_ACCOUNT_KIND, name="ck_finance_accounts_kind"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(schema.ACCOUNT_MAX), nullable=False)
    name: Mapped[str] = mapped_column(String(schema.ACCOUNT_NAME_MAX), nullable=False)
    kind: Mapped[str] = mapped_column(String(12), nullable=False)
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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


class FinancePostingRule(Base):
    __tablename__ = "finance_posting_rules"
    __table_args__ = (
        CheckConstraint(
            schema.CK_RULE_CATEGORY, name="ck_finance_posting_rules_category"
        ),
        CheckConstraint(
            schema.CK_RULE_DEDUCTION, name="ck_finance_posting_rules_deduction"
        ),
        CheckConstraint(
            schema.CK_RULE_REGISTER, name="ck_finance_posting_rules_register"
        ),
        CheckConstraint(schema.CK_RULE_VAT, name="ck_finance_posting_rules_vat"),
        Index(
            "uq_finance_posting_rules_general",
            "category",
            unique=True,
            postgresql_where=text(schema.RULE_GENERAL_WHERE),
        ),
        Index(
            "uq_finance_posting_rules_counterparty",
            "category",
            "counterparty_id",
            unique=True,
            postgresql_where=text(schema.RULE_COUNTERPARTY_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    category: Mapped[str] = mapped_column(String(12), nullable=False)
    counterparty_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_counterparties.id", ondelete="CASCADE"), nullable=True
    )
    cost_account: Mapped[str] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=False
    )
    vat_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    deduction: Mapped[str] = mapped_column(String(8), nullable=False)
    register: Mapped[str] = mapped_column(String(10), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(schema.DOC_TYPE_MAX), nullable=False)
    service_label: Mapped[str] = mapped_column(
        String(schema.SERVICE_MAX), nullable=False
    )
    description_template: Mapped[str] = mapped_column(
        String(schema.TEMPLATE_MAX), nullable=False
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
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


class FinancePostingBatch(Base):
    __tablename__ = "finance_posting_batches"
    __table_args__ = (
        UniqueConstraint("number", name="uq_finance_posting_batches_number"),
        CheckConstraint(
            schema.CK_BATCH_STATUS, name="ck_finance_posting_batches_status"
        ),
        Index("ix_finance_posting_batches_month", "month", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    number: Mapped[str] = mapped_column(String(schema.BATCH_NUMBER_MAX), nullable=False)
    month: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    file_format: Mapped[str] = mapped_column(String(20), nullable=False)
    file_name: Mapped[str] = mapped_column(String(schema.FILE_NAME_MAX), nullable=False)
    file_content: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    file_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    entry_ids: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)
    entry_count: Mapped[int] = mapped_column(Integer, nullable=False)
    debit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
    credit_total: Mapped[int] = mapped_column(BigInteger, nullable=False)
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
