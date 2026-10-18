"""Faktury sprzedażowe do klientów z KSeF (0470, etap 5 — E8 cz. 1).

CHECK-i i indeksy muszą być identyczne z ``app/services/client_sales_invoices_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis tabel i stanów
— w docstringu modułu schematu.

* ``ClientSalesInvoice`` — faktura z KSeF, w której spółka jest sprzedawcą,
* ``ClientSalesInvoiceLink`` — powiązanie faktury z zamówieniem w miesiącu usługi,
* ``ClientSalesInvoicePayment`` — zapłata: uznanie z wyciągu albo ręczne „opłacono”.
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import client_sales_invoices_schema as schema


class ClientSalesInvoice(Base, TimestampMixin):
    """Faktura do klienta odczytana z KSeF (spółka jako sprzedawca)."""

    __tablename__ = "client_sales_invoices"
    __table_args__ = (
        CheckConstraint(
            schema.CK_INVOICE_KSEF_NUMBER,
            name="ck_client_sales_invoices_ksef_number",
        ),
        CheckConstraint(
            schema.CK_INVOICE_XML_HASH, name="ck_client_sales_invoices_xml_hash"
        ),
        CheckConstraint(
            schema.CK_INVOICE_BUYER_NIP, name="ck_client_sales_invoices_buyer_nip"
        ),
        CheckConstraint(schema.CK_INVOICE_KIND, name="ck_client_sales_invoices_kind"),
        CheckConstraint(
            schema.CK_INVOICE_CURRENCY, name="ck_client_sales_invoices_currency"
        ),
        CheckConstraint(
            schema.CK_INVOICE_AMOUNTS, name="ck_client_sales_invoices_amounts"
        ),
        CheckConstraint(
            schema.CK_INVOICE_PERIOD, name="ck_client_sales_invoices_period"
        ),
        CheckConstraint(schema.CK_INVOICE_ITEMS, name="ck_client_sales_invoices_items"),
        CheckConstraint(schema.CK_INVOICE_MATCH, name="ck_client_sales_invoices_match"),
        CheckConstraint(
            schema.CK_INVOICE_METHOD, name="ck_client_sales_invoices_method"
        ),
        CheckConstraint(
            schema.CK_INVOICE_MATCHED, name="ck_client_sales_invoices_matched"
        ),
        CheckConstraint(
            schema.CK_INVOICE_IGNORED, name="ck_client_sales_invoices_ignored"
        ),
        CheckConstraint(
            schema.CK_INVOICE_DIFFERENCE, name="ck_client_sales_invoices_difference"
        ),
        Index("uq_client_sales_invoices_ksef_number", "ksef_number", unique=True),
        Index(
            "ix_client_sales_invoices_client_period",
            "client_id",
            "period_year",
            "period_month",
        ),
        Index("ix_client_sales_invoices_match", "match_status", "issue_date"),
        Index(
            "ix_client_sales_invoices_corrects",
            "corrects_invoice_id",
            postgresql_where=text("corrects_invoice_id IS NOT NULL"),
        ),
        Index(
            "ix_client_sales_invoices_buyer_nip",
            "buyer_nip",
            postgresql_where=text("buyer_nip IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ksef_number: Mapped[str] = mapped_column(
        String(schema.KSEF_NUMBER_MAX), nullable=False
    )
    ksef_acquired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    xml_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    buyer_nip: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    buyer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(String(256), nullable=False)
    invoice_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="VAT", server_default="VAT"
    )
    invoice_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="original", server_default="original"
    )
    corrects_invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_sales_invoices.id", ondelete="SET NULL"), nullable=True
    )
    corrected_ksef_number: Mapped[Optional[str]] = mapped_column(
        String(schema.KSEF_NUMBER_MAX), nullable=True
    )
    corrected_invoice_number: Mapped[Optional[str]] = mapped_column(
        String(256), nullable=True
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    period_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    period_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    paid_in_invoice_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    net_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    vat_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    gross_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    items: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    #: Teksty z faktury, w których szukamy numeru zamówienia (zamówienia,
    #: umowy, opis dodatkowy) — pozycje są w ``items``.
    order_refs: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    match_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unmatched", server_default="unmatched"
    )
    match_method: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    match_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.MATCH_REASON_MAX), nullable=True
    )
    matched_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    matched_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    ignore_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    difference_accepted_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    difference_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    difference_accepted_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    difference_accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientSalesInvoiceLink(Base):
    """Faktura ↔ zamówienie (całe zamówienie klienta albo jedno) w miesiącu usługi."""

    __tablename__ = "client_sales_invoice_links"
    __table_args__ = (
        CheckConstraint(
            schema.CK_LINK_TARGET, name="ck_client_sales_invoice_links_target"
        ),
        CheckConstraint(
            schema.CK_LINK_PERIOD, name="ck_client_sales_invoice_links_period"
        ),
        Index(
            "uq_client_sales_invoice_links_group",
            "invoice_id",
            "order_group_id",
            unique=True,
            postgresql_where=text(schema.LINK_GROUP_WHERE),
        ),
        Index(
            "uq_client_sales_invoice_links_order",
            "invoice_id",
            "order_id",
            unique=True,
            postgresql_where=text(schema.LINK_ORDER_WHERE),
        ),
        Index(
            "ix_client_sales_invoice_links_group_period",
            "order_group_id",
            "period_year",
            "period_month",
            postgresql_where=text(schema.LINK_GROUP_WHERE),
        ),
        Index(
            "ix_client_sales_invoice_links_order_period",
            "order_id",
            "period_year",
            "period_month",
            postgresql_where=text(schema.LINK_ORDER_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("client_sales_invoices.id", ondelete="CASCADE"), nullable=False
    )
    order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="CASCADE"), nullable=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=True
    )
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ClientSalesInvoicePayment(Base):
    """Zapłata faktury do klienta: uznanie z wyciągu albo ręczne „opłacono”."""

    __tablename__ = "client_sales_invoice_payments"
    __table_args__ = (
        CheckConstraint(
            schema.CK_PAYMENT_KIND, name="ck_client_sales_invoice_payments_kind"
        ),
        CheckConstraint(
            schema.CK_PAYMENT_MATCH, name="ck_client_sales_invoice_payments_match"
        ),
        CheckConstraint(
            schema.CK_PAYMENT_MATCHED, name="ck_client_sales_invoice_payments_matched"
        ),
        CheckConstraint(
            schema.CK_PAYMENT_CURRENCY,
            name="ck_client_sales_invoice_payments_currency",
        ),
        CheckConstraint(
            schema.CK_PAYMENT_AMOUNT, name="ck_client_sales_invoice_payments_amount"
        ),
        CheckConstraint(
            schema.CK_PAYMENT_STATEMENT,
            name="ck_client_sales_invoice_payments_statement",
        ),
        CheckConstraint(
            schema.CK_PAYMENT_MANUAL, name="ck_client_sales_invoice_payments_manual"
        ),
        CheckConstraint(
            schema.CK_PAYMENT_IGNORED, name="ck_client_sales_invoice_payments_ignored"
        ),
        Index(
            "uq_client_sales_invoice_payments_statement",
            "statement_sha256",
            "statement_line_ref",
            unique=True,
            postgresql_where=text(schema.STATEMENT_LINE_WHERE),
        ),
        Index("ix_client_sales_invoice_payments_invoice", "invoice_id"),
        Index("ix_client_sales_invoice_payments_match", "match_status", "booked_on"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_sales_invoices.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    match_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unmatched", server_default="unmatched"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    booked_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    title: Mapped[Optional[str]] = mapped_column(
        String(schema.TITLE_MAX_LENGTH), nullable=True
    )
    counterparty_name: Mapped[Optional[str]] = mapped_column(
        String(schema.COUNTERPARTY_MAX_LENGTH), nullable=True
    )
    statement_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    statement_format: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    statement_line_ref: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
