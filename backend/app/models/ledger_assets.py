"""Środki trwałe i WNiP (K6, 0703): ewidencja i dokumenty środka.

CHECK-i i indeksy muszą być identyczne z ``app/services/ledger_assets_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Opis tabel — w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import ledger_assets_schema as schema
from app.services.ledger_schema import ACCOUNT_MAX, MPK_MAX


class LedgerAsset(Base):
    """Środek trwały albo WNiP w ewidencji (K6)."""

    __tablename__ = "ledger_assets"
    __table_args__ = (
        UniqueConstraint("inventory_number", name="uq_ledger_assets_inventory"),
        CheckConstraint(schema.CK_ASSET_KIND, name="ck_ledger_assets_kind"),
        CheckConstraint(schema.CK_ASSET_STATUS, name="ck_ledger_assets_status"),
        CheckConstraint(schema.CK_ASSET_DISPOSED, name="ck_ledger_assets_disposed"),
        CheckConstraint(schema.CK_ASSET_VALUE, name="ck_ledger_assets_value"),
        CheckConstraint(schema.CK_ASSET_METHODS, name="ck_ledger_assets_methods"),
        CheckConstraint(schema.CK_ASSET_RATES, name="ck_ledger_assets_rates"),
        CheckConstraint(
            schema.CK_ASSET_COEFFICIENT, name="ck_ledger_assets_coefficient"
        ),
        CheckConstraint(schema.CK_ASSET_OPENING, name="ck_ledger_assets_opening"),
        Index(
            "ux_ledger_assets_equipment",
            "equipment_item_id",
            unique=True,
            postgresql_where=text(schema.ASSET_EQUIPMENT_WHERE),
        ),
        Index("ix_ledger_assets_status", "status", "accepted_on"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inventory_number: Mapped[str] = mapped_column(
        String(schema.INVENTORY_MAX), nullable=False
    )
    name: Mapped[str] = mapped_column(String(schema.NAME_MAX), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(10), nullable=False, default="fixed", server_default=text("'fixed'")
    )
    kst: Mapped[Optional[str]] = mapped_column(String(schema.KST_MAX), nullable=True)
    accepted_on: Mapped[date] = mapped_column(Date, nullable=False)
    initial_value: Mapped[int] = mapped_column(BigInteger, nullable=False)
    asset_account: Mapped[str] = mapped_column(String(ACCOUNT_MAX), nullable=False)
    depreciation_account: Mapped[str] = mapped_column(
        String(ACCOUNT_MAX), nullable=False
    )
    mpk: Mapped[str] = mapped_column(String(MPK_MAX), nullable=False)
    balance_method: Mapped[str] = mapped_column(String(10), nullable=False)
    balance_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    tax_method: Mapped[str] = mapped_column(String(10), nullable=False)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    coefficient: Mapped[Decimal] = mapped_column(
        Numeric(3, 2), nullable=False, default=Decimal("2.0"), server_default="2.0"
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="in_use", server_default=text("'in_use'")
    )
    disposed_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    equipment_item_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("equipment_items.id", ondelete="SET NULL"), nullable=True
    )
    opening_month: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    opening_balance: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    opening_tax: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    opening_balance_year: Mapped[Optional[int]] = mapped_column(
        BigInteger, nullable=True
    )
    opening_tax_year: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str] = mapped_column(
        String(schema.NOTE_MAX), nullable=False, default="", server_default=""
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


class LedgerAssetOperation(Base):
    """Dokument środka: OT, ulepszenie, zmiana MPK, likwidacja, sprzedaż (K6)."""

    __tablename__ = "ledger_asset_operations"
    __table_args__ = (
        UniqueConstraint("number", name="uq_ledger_asset_operations_number"),
        CheckConstraint(
            schema.CK_OPERATION_TYPE, name="ck_ledger_asset_operations_type"
        ),
        CheckConstraint(
            schema.CK_OPERATION_AMOUNT, name="ck_ledger_asset_operations_amount"
        ),
        CheckConstraint(schema.CK_OPERATION_MPK, name="ck_ledger_asset_operations_mpk"),
        Index("ix_ledger_asset_operations_asset", "asset_id", "op_date"),
        Index("ix_ledger_asset_operations_month", "op_date"),
        Index(
            "ix_ledger_asset_operations_cost",
            "cost_entry_id",
            postgresql_where=text(schema.OPERATION_COST_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    asset_id: Mapped[int] = mapped_column(
        ForeignKey("ledger_assets.id", ondelete="CASCADE"), nullable=False
    )
    op_type: Mapped[str] = mapped_column(String(2), nullable=False)
    number: Mapped[str] = mapped_column(
        String(schema.OPERATION_NUMBER_MAX), nullable=False
    )
    op_date: Mapped[date] = mapped_column(Date, nullable=False)
    amount: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    mpk_from: Mapped[Optional[str]] = mapped_column(String(MPK_MAX), nullable=True)
    mpk_to: Mapped[Optional[str]] = mapped_column(String(MPK_MAX), nullable=True)
    counter_account: Mapped[Optional[str]] = mapped_column(
        String(ACCOUNT_MAX), nullable=True
    )
    cost_entry_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("finance_cost_entries.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(
        String(schema.OPERATION_TITLE_MAX),
        nullable=False,
        default="",
        server_default="",
    )
    note: Mapped[str] = mapped_column(
        String(schema.OPERATION_NOTE_MAX), nullable=False, default="", server_default=""
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
