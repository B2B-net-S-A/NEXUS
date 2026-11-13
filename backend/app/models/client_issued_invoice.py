"""Faktury sprzedaży wystawiane w NEXUSIE i wysyłane do KSeF (0696, E4).

CHECK-i i indeksy muszą być identyczne z ``app/services/client_invoice_issue_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis tabel i stanów
— w docstringu modułu schematu.

* ``ClientInvoiceSeries`` — następny numer serii w miesiącu (blokada wiersza przy nadaniu),
* ``ClientIssuedInvoice`` — faktura od szkicu do przyjęcia w KSeF.
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
    PrimaryKeyConstraint,
    SmallInteger,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import client_invoice_issue_schema as schema
from app.services.client_sales_invoices_schema import KSEF_NUMBER_MAX


class ClientInvoiceSeries(Base):
    """Licznik numeracji: seria × miesiąc daty wystawienia → następny numer."""

    __tablename__ = "client_invoice_series"
    __table_args__ = (
        PrimaryKeyConstraint("series_code", "period_year", "period_month"),
        CheckConstraint(schema.CK_SERIES_CODE, name="ck_client_invoice_series_code"),
        CheckConstraint(
            schema.CK_SERIES_PERIOD, name="ck_client_invoice_series_period"
        ),
        CheckConstraint(schema.CK_SERIES_NEXT, name="ck_client_invoice_series_next"),
    )

    series_code: Mapped[str] = mapped_column(String(8), nullable=False)
    period_year: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    period_month: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    next_number: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class ClientIssuedInvoice(Base, TimestampMixin):
    """Faktura sprzedaży wystawiana w NEXUSIE (szkic → KSeF → przyjęta)."""

    __tablename__ = "client_issued_invoices"
    __table_args__ = (
        CheckConstraint(schema.CK_ISSUED_TYPE, name="ck_client_issued_invoices_type"),
        CheckConstraint(
            schema.CK_ISSUED_SERIES, name="ck_client_issued_invoices_series"
        ),
        CheckConstraint(
            schema.CK_ISSUED_STATUS, name="ck_client_issued_invoices_status"
        ),
        CheckConstraint(
            schema.CK_ISSUED_CURRENCY, name="ck_client_issued_invoices_currency"
        ),
        CheckConstraint(
            schema.CK_ISSUED_NUMBER, name="ck_client_issued_invoices_number"
        ),
        CheckConstraint(schema.CK_ISSUED_DRAFT, name="ck_client_issued_invoices_draft"),
        CheckConstraint(
            schema.CK_ISSUED_ACCEPTED, name="ck_client_issued_invoices_accepted"
        ),
        CheckConstraint(
            schema.CK_ISSUED_CORRECTION, name="ck_client_issued_invoices_correction"
        ),
        CheckConstraint(
            schema.CK_ISSUED_PERIOD, name="ck_client_issued_invoices_period"
        ),
        CheckConstraint(schema.CK_ISSUED_JSON, name="ck_client_issued_invoices_json"),
        CheckConstraint(
            schema.CK_ISSUED_AMOUNTS, name="ck_client_issued_invoices_amounts"
        ),
        Index(
            "uq_client_issued_invoices_number",
            "series_code",
            "number_year",
            "number_month",
            "number_seq",
            unique=True,
            postgresql_where=text(schema.NUMBERED_WHERE),
        ),
        Index(
            "uq_client_issued_invoices_ksef_number",
            "ksef_number",
            unique=True,
            postgresql_where=text(schema.KSEF_WHERE),
        ),
        Index("ix_client_issued_invoices_status", "status", "issue_date"),
        Index("ix_client_issued_invoices_client", "client_id"),
        Index(
            "ix_client_issued_invoices_group_period",
            "order_group_id",
            "period_year",
            "period_month",
            postgresql_where=text(schema.GROUP_WHERE),
        ),
        Index(
            "ix_client_issued_invoices_corrects",
            "corrects_id",
            postgresql_where=text(schema.CORRECTS_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="RESTRICT"), nullable=False
    )
    invoice_type: Mapped[str] = mapped_column(
        String(8), nullable=False, default="VAT", server_default="VAT"
    )
    series_code: Mapped[str] = mapped_column(
        String(8), nullable=False, default="PL", server_default="PL"
    )
    status: Mapped[str] = mapped_column(
        String(12), nullable=False, default="draft", server_default="draft"
    )
    number_seq: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    number_year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    number_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    invoice_number: Mapped[Optional[str]] = mapped_column(
        String(schema.INVOICE_NUMBER_MAX), nullable=True
    )
    order_group_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_order_groups.id", ondelete="SET NULL"), nullable=True
    )
    order_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_orders.id", ondelete="SET NULL"), nullable=True
    )
    period_year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    period_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    corrects_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_issued_invoices.id", ondelete="RESTRICT"), nullable=True
    )
    correction_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX), nullable=True
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_from: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    due_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    client_order_number: Mapped[Optional[str]] = mapped_column(
        String(schema.ORDER_NUMBER_MAX), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(
        String(schema.NOTES_MAX), nullable=True
    )
    buyer: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    lines: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    lines_before: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    vat_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(14, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    fx_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 6), nullable=True)
    fx_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    xml_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ksef_environment: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    ksef_session_ref: Mapped[Optional[str]] = mapped_column(
        String(schema.REF_MAX), nullable=True
    )
    ksef_invoice_ref: Mapped[Optional[str]] = mapped_column(
        String(schema.REF_MAX), nullable=True
    )
    ksef_number: Mapped[Optional[str]] = mapped_column(
        String(KSEF_NUMBER_MAX), nullable=True
    )
    ksef_status_code: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    ksef_status_text: Mapped[Optional[str]] = mapped_column(
        String(schema.STATUS_TEXT_MAX), nullable=True
    )
    ksef_acquired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    upo_xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sales_invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("client_sales_invoices.id", ondelete="SET NULL"), nullable=True
    )
    history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    accepted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
