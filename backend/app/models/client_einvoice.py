"""E-faktura Peppol przy fakturze sprzedażowej z KSeF (0690, plan Nordei N2).

CHECK-i i indeksy muszą być identyczne z ``app/services/client_einvoices_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis stanów —
w docstringu modułu schematu.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import client_einvoices_schema as schema


class ClientSalesInvoiceEinvoice(Base, TimestampMixin):
    __tablename__ = "client_sales_invoice_einvoices"
    __table_args__ = (
        CheckConstraint(schema.CK_STATUS, name="ck_client_sales_invoice_einvoices_status"),
        CheckConstraint(
            schema.CK_DOCUMENT_TYPE,
            name="ck_client_sales_invoice_einvoices_document_type",
        ),
        CheckConstraint(schema.CK_TARGET, name="ck_client_sales_invoice_einvoices_target"),
        CheckConstraint(schema.CK_SENT, name="ck_client_sales_invoice_einvoices_sent"),
        Index("uq_client_sales_invoice_einvoices_invoice", "invoice_id", unique=True),
        Index("ix_client_sales_invoice_einvoices_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    invoice_id: Mapped[int] = mapped_column(
        ForeignKey("client_sales_invoices.id", ondelete="CASCADE"), nullable=False
    )
    receiver_key: Mapped[str] = mapped_column(
        String(schema.RECEIVER_KEY_MAX), nullable=False
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    document_type: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    fa_xml: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    xml_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    problems: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    target: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    recipient: Mapped[Optional[str]] = mapped_column(
        String(schema.RECIPIENT_MAX), nullable=True
    )
    provider: Mapped[Optional[str]] = mapped_column(
        String(schema.PROVIDER_MAX), nullable=True
    )
    provider_document_id: Mapped[Optional[str]] = mapped_column(
        String(schema.PROVIDER_ID_MAX), nullable=True
    )
    delivery_detail: Mapped[Optional[str]] = mapped_column(
        String(schema.DETAIL_MAX), nullable=True
    )
    ubl_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    history: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )


__all__ = ["ClientSalesInvoiceEinvoice"]
