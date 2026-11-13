"""Rozliczenia klientów (E1, E4, E5.1): rozliczenie osoby za miesiąc, wersje reguł
klienta, faktury kontraktorów z KSeF i dodatki do rozliczenia (koszty integracji).

CHECK-i i indeksy jak w ``app/services/client_settlements_schema.py`` (strażnik
dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    Boolean,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import client_settlement_extras_schema as extras_schema
from app.services import client_settlements_schema as schema


class ClientSettlement(Base):
    __tablename__ = "client_settlements"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "period_month",
            "kind",
            name="uq_client_settlements_contract_month",
        ),
        CheckConstraint(schema.PERIOD_CHECK, name="ck_client_settlements_period"),
        CheckConstraint(schema.CK_KIND, name="ck_client_settlements_kind"),
        CheckConstraint(schema.CK_STATUS, name="ck_client_settlements_status"),
        CheckConstraint(schema.CK_LINES_ARRAY, name="ck_client_settlements_lines"),
        CheckConstraint(schema.CK_CHECKS_ARRAY, name="ck_client_settlements_checks"),
        CheckConstraint(
            schema.CK_SETTLEMENT_MD_SOURCE, name="ck_client_settlements_md_source"
        ),
        Index("ix_client_settlements_client_month", "client_id", "period_month"),
        Index(
            "ix_client_settlements_order",
            "order_id",
            postgresql_where=text("order_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(8), nullable=False, server_default="actual", default="actual"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="checking", default="checking"
    )
    report_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cp_documents.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    md_regular: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    md_extra: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    md_onboarding: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(10, 3), nullable=True
    )
    md_charged: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 3), nullable=True)
    md_source: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    amount_cost: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    amount_revenue: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    lines: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    checks: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    fix_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.FIX_REASON_MAX), nullable=True
    )
    accepted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
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


class ClientSettlementRuleSet(Base):
    __tablename__ = "client_settlement_rule_sets"
    __table_args__ = (
        UniqueConstraint(
            "client_id", "effective_from", name="uq_client_settlement_rule_sets_from"
        ),
        CheckConstraint(schema.FROM_CHECK, name="ck_client_settlement_rule_sets_from"),
        CheckConstraint(
            schema.CK_RULES_OBJECT, name="ck_client_settlement_rule_sets_rules"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[str] = mapped_column(String(7), nullable=False)
    rules: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"), default=dict
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


class ClientContractorInvoice(Base):
    __tablename__ = "client_contractor_invoices"
    __table_args__ = (
        UniqueConstraint("ksef_number", name="uq_client_contractor_invoices_ksef"),
        CheckConstraint(
            f"period_month IS NULL OR {schema.PERIOD_CHECK}",
            name="ck_client_contractor_invoices_period",
        ),
        CheckConstraint(
            schema.CK_NIP_STATE, name="ck_client_contractor_invoices_nip_state"
        ),
        Index(
            "ix_client_contractor_invoices_contract_month",
            "contract_id",
            "period_month",
        ),
        Index("ix_client_contractor_invoices_seller", "seller_nip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ksef_number: Mapped[str] = mapped_column(String(64), nullable=False)
    seller_nip: Mapped[str] = mapped_column(String(10), nullable=False)
    seller_name: Mapped[Optional[str]] = mapped_column(
        String(schema.SELLER_NAME_MAX), nullable=True
    )
    buyer_nip: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(
        String(schema.INVOICE_NUMBER_MAX), nullable=True
    )
    invoice_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    acquired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, server_default="PLN", default="PLN"
    )
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    vat_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    contract_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contracts.id", ondelete="SET NULL"), nullable=True
    )
    period_month: Mapped[Optional[str]] = mapped_column(String(7), nullable=True)
    nip_state: Mapped[str] = mapped_column(String(10), nullable=False)
    #: Treść z XML-a FA (korekty i faktury korygowane): ``state``, ``items``,
    #: ``corrected``, ``reason`` — ``contractor_details.py``.
    details: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    #: Status sprzedawcy na białej liście VAT na dzień wystawienia.
    vat_whitelist: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
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


class ClientSettlementExtra(Base):
    """Dodatek do rozliczenia osoby w miesiącu; rodzaj ``integration`` to koszt
    integracji na koszt B2B (reguła ``cl.integration_costs``)."""

    __tablename__ = "client_settlement_extras"
    __table_args__ = (
        CheckConstraint(schema.PERIOD_CHECK, name="ck_client_settlement_extras_period"),
        CheckConstraint(schema.CK_EXTRA_KIND, name="ck_client_settlement_extras_kind"),
        CheckConstraint(
            schema.CK_EXTRA_STATUS,
            name="ck_client_settlement_extras_status",
        ),
        CheckConstraint(
            schema.CK_EXTRA_AMOUNT,
            name="ck_client_settlement_extras_amount",
        ),
        Index(
            "ix_client_settlement_extras_contract",
            "contract_id",
            "period_month",
        ),
        Index(
            "ix_client_settlement_extras_client",
            "client_id",
            "period_month",
        ),
        CheckConstraint(
            extras_schema.CK_SOURCE, name="ck_client_settlement_extras_source"
        ),
        Index(
            "ix_client_settlement_extras_card",
            "bo_card_id",
            postgresql_where=text("bo_card_id IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    kind: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="integration", default="integration"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    description: Mapped[str] = mapped_column(
        String(schema.EXTRA_DESCRIPTION_MAX), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="pending", default="pending"
    )
    # 0690: źródło zgłoszenia, karta sprawy, fakturowanie klientowi, powód decyzji
    # (``client_settlement_extras_schema``).
    source: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default="finance", default="finance"
    )
    bo_card_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("bo_cards.id", ondelete="SET NULL"), nullable=True
    )
    bill_to_client: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false"), default=False
    )
    decision_note: Mapped[Optional[str]] = mapped_column(
        String(extras_schema.DECISION_NOTE_MAX), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
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
