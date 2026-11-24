"""Zajęcia wierzytelności kontraktora i „Spór / wstrzymane” na rozliczeniu (0765).

CHECK-i i indeksy muszą być identyczne z
``app/services/contractor_payment_blocks_schema.py`` (raport ``compare_metadata``
w ``/api/health/deep`` porównuje model z bazą). Opis tabel — w docstringu
modułu schematu.
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
    String,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import contractor_payment_blocks_schema as schema


class ContractorGarnishment(Base):
    __tablename__ = "contractor_garnishments"
    __table_args__ = (
        CheckConstraint(
            schema.CK_AUTHORITY_KIND, name="ck_contractor_garnishments_authority_kind"
        ),
        CheckConstraint(
            schema.CK_INTEREST_MODE, name="ck_contractor_garnishments_interest_mode"
        ),
        CheckConstraint(
            schema.CK_PRINCIPAL, name="ck_contractor_garnishments_principal"
        ),
        CheckConstraint(schema.CK_COSTS, name="ck_contractor_garnishments_costs"),
        CheckConstraint(
            schema.CK_INTEREST_AMOUNT,
            name="ck_contractor_garnishments_interest_amount",
        ),
        CheckConstraint(
            schema.CK_INTEREST_RATE, name="ck_contractor_garnishments_interest_rate"
        ),
        Index("ix_contractor_garnishments_contract", "contract_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    authority_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    authority_name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    case_number: Mapped[str] = mapped_column(String(schema.CASE_MAX), nullable=False)
    served_on: Mapped[date] = mapped_column(Date, nullable=False)
    principal_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    costs_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    interest_mode: Mapped[str] = mapped_column(
        String(10), nullable=False, default="unknown", server_default="unknown"
    )
    interest_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    interest_rate: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(6, 3), nullable=True
    )
    interest_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    authority_account: Mapped[Optional[str]] = mapped_column(
        String(schema.ACCOUNT_MAX), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(schema.NOTE_MAX), nullable=True)
    lifted_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    lifted_note: Mapped[Optional[str]] = mapped_column(
        String(schema.NOTE_MAX), nullable=True
    )
    lifted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    lifted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContractorPaymentHold(Base):
    __tablename__ = "contractor_payment_holds"
    __table_args__ = (
        Index(
            "uq_contractor_payment_holds_active",
            "settlement_id",
            unique=True,
            postgresql_where=text(schema.ACTIVE_HOLD_WHERE),
        ),
        Index("ix_contractor_payment_holds_settlement", "settlement_id", "id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    settlement_id: Mapped[int] = mapped_column(
        ForeignKey("client_settlements.id", ondelete="CASCADE"), nullable=False
    )
    reason: Mapped[str] = mapped_column(String(schema.NOTE_MAX), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    released_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    released_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    release_note: Mapped[Optional[str]] = mapped_column(
        String(schema.NOTE_MAX), nullable=True
    )
