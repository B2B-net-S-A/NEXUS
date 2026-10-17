"""„Ludzie w NEXUSIE” — modele: Rozliczenia zespołu (0466).

CHECK-i i indeksy muszą być identyczne z ``app/services/hr_settlement_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji). Opis tabel i stanów
— w docstringu modułu schematu.

* ``EmployeeBillingDetails`` — dane do rozliczeń osoby (NIP, wykaz VAT, rachunek
  zaszyfrowany, termin płatności, identyfikator w Symfonii),
* ``PayrollSettlement`` — rozliczenie osoby za zamknięty miesiąc (osoba × waluta),
* ``PayrollInvoice`` — faktura od osoby (KSeF albo PDF dopięty ręcznie),
* ``PayrollPayment`` — zdarzenie płatności (paczka, wiersz wyciągu, ręcznie).
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_settlement_schema as schema


class EmployeeBillingDetails(Base, TimestampMixin):
    """Dane do rozliczeń osoby — widzą osoba, Kadry i Płace."""

    __tablename__ = "employee_billing_details"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_employee_billing_details_user"),
        CheckConstraint(schema.CK_BILLING_NIP, name="ck_employee_billing_details_nip"),
        CheckConstraint(
            schema.CK_BILLING_VAT_STATUS,
            name="ck_employee_billing_details_vat_status",
        ),
        CheckConstraint(
            schema.CK_BILLING_ACCOUNT, name="ck_employee_billing_details_account"
        ),
        CheckConstraint(
            schema.CK_BILLING_WHITE_LIST,
            name="ck_employee_billing_details_white_list",
        ),
        CheckConstraint(
            schema.CK_BILLING_TERMS, name="ck_employee_billing_details_terms"
        ),
        CheckConstraint(
            schema.CK_BILLING_SYMFONIA, name="ck_employee_billing_details_symfonia"
        ),
        Index(
            "ix_employee_billing_details_nip",
            "nip",
            postgresql_where=text("nip IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    nip: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    registry_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    vat_status: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    vat_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Rachunek zaszyfrowany ``TokenCipher`` — nigdy w logach ani w audycie.
    account_encrypted: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    account_last4: Mapped[Optional[str]] = mapped_column(String(4), nullable=True)
    account_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    account_check_request_id: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    account_checked_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    payment_terms_days: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=14, server_default="14"
    )
    #: GUID albo numer ewidencyjny osoby w Symfonii (bez PESEL-u).
    symfonia_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PayrollSettlement(Base, TimestampMixin):
    """Rozliczenie osoby za zamknięty miesiąc (osoba × waluta)."""

    __tablename__ = "payroll_settlements"
    __table_args__ = (
        CheckConstraint(schema.CK_SETTLEMENT_TYPE, name="ck_payroll_settlements_type"),
        CheckConstraint(
            schema.CK_SETTLEMENT_CURRENCY, name="ck_payroll_settlements_currency"
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_STATUS, name="ck_payroll_settlements_status"
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_BASIS, name="ck_payroll_settlements_basis"
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_AMOUNT, name="ck_payroll_settlements_amount"
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_AWAITING, name="ck_payroll_settlements_awaiting"
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_OVERRIDE_KIND,
            name="ck_payroll_settlements_override_kind",
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_OVERRIDE_REASON,
            name="ck_payroll_settlements_override_reason",
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_OVERRIDE_TWO_PEOPLE,
            name="ck_payroll_settlements_override_two_people",
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_NOT_SELF_APPROVED,
            name="ck_payroll_settlements_not_self_approved",
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_APPROVED, name="ck_payroll_settlements_approved"
        ),
        CheckConstraint(schema.CK_SETTLEMENT_PAID, name="ck_payroll_settlements_paid"),
        CheckConstraint(
            schema.CK_SETTLEMENT_PAID_REASON,
            name="ck_payroll_settlements_paid_reason",
        ),
        CheckConstraint(
            schema.CK_SETTLEMENT_CANCELLED, name="ck_payroll_settlements_cancelled"
        ),
        Index(
            "uq_payroll_settlements_live",
            "period_id",
            "user_id",
            "currency",
            unique=True,
            postgresql_where=text(schema.LIVE_SETTLEMENT_WHERE),
        ),
        Index("ix_payroll_settlements_status", "status", "due_on"),
        Index("ix_payroll_settlements_user", "user_id", "period_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_id: Mapped[int] = mapped_column(
        ForeignKey("payroll_periods.id", ondelete="RESTRICT"), nullable=False
    )
    line_id: Mapped[Optional[int]] = mapped_column(
        BigInteger, ForeignKey("payroll_lines.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    employment_type: Mapped[str] = mapped_column(String(16), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    amount_basis: Mapped[str] = mapped_column(String(8), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    due_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    #: Skrót PDF rozliczenia zlecenia (dokument, który może służyć jako rachunek).
    document_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    discrepancy_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    correction_requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    correction_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    override_kind: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    override_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    override_requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    override_confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    override_confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    paid_source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    paid_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    paid_reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    paid_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PayrollInvoice(Base, TimestampMixin):
    """Faktura od osoby: z KSeF albo PDF dopięty ręcznie przez Płace."""

    __tablename__ = "payroll_invoices"
    __table_args__ = (
        CheckConstraint(schema.CK_INVOICE_SOURCE, name="ck_payroll_invoices_source"),
        CheckConstraint(schema.CK_INVOICE_KSEF, name="ck_payroll_invoices_ksef"),
        CheckConstraint(schema.CK_INVOICE_PDF, name="ck_payroll_invoices_pdf"),
        CheckConstraint(
            schema.CK_INVOICE_SELLER_NIP, name="ck_payroll_invoices_seller_nip"
        ),
        CheckConstraint(schema.CK_INVOICE_KIND, name="ck_payroll_invoices_kind"),
        CheckConstraint(
            schema.CK_INVOICE_CURRENCY, name="ck_payroll_invoices_currency"
        ),
        CheckConstraint(schema.CK_INVOICE_AMOUNTS, name="ck_payroll_invoices_amounts"),
        CheckConstraint(schema.CK_INVOICE_PERIOD, name="ck_payroll_invoices_period"),
        CheckConstraint(schema.CK_INVOICE_ITEMS, name="ck_payroll_invoices_items"),
        CheckConstraint(schema.CK_INVOICE_MATCH, name="ck_payroll_invoices_match"),
        CheckConstraint(
            schema.CK_INVOICE_MATCHED, name="ck_payroll_invoices_matched"
        ),
        CheckConstraint(schema.CK_INVOICE_HASHES, name="ck_payroll_invoices_hashes"),
        Index(
            "uq_payroll_invoices_ksef_number",
            "ksef_number",
            unique=True,
            postgresql_where=text(schema.KSEF_NUMBER_WHERE),
        ),
        Index(
            "ix_payroll_invoices_seller_period",
            "seller_nip",
            "period_year",
            "period_month",
        ),
        Index("ix_payroll_invoices_settlement", "settlement_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    ksef_number: Mapped[Optional[str]] = mapped_column(
        String(schema.KSEF_NUMBER_MAX), nullable=True
    )
    #: Data przyjęcia do KSeF (znacznik przyrostowego pobierania).
    ksef_acquired_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    seller_nip: Mapped[str] = mapped_column(String(10), nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    invoice_number: Mapped[str] = mapped_column(String(256), nullable=False)
    invoice_kind: Mapped[str] = mapped_column(
        String(16), nullable=False, default="original", server_default="original"
    )
    corrects_invoice_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payroll_invoices.id", ondelete="SET NULL"), nullable=True
    )
    corrected_ksef_number: Mapped[Optional[str]] = mapped_column(
        String(schema.KSEF_NUMBER_MAX), nullable=True
    )
    issue_date: Mapped[date] = mapped_column(Date, nullable=False)
    sale_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    period_year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    period_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
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
    xml_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    pdf_storage_key: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    pdf_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    settlement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payroll_settlements.id", ondelete="SET NULL"), nullable=True
    )
    match_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="unmatched", server_default="unmatched"
    )
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PayrollPayment(Base):
    """Zdarzenie płatności: wiersz paczki przelewów, wiersz wyciągu albo ręcznie."""

    __tablename__ = "payroll_payments"
    __table_args__ = (
        CheckConstraint(schema.CK_PAYMENT_KIND, name="ck_payroll_payments_kind"),
        CheckConstraint(schema.CK_PAYMENT_MATCH, name="ck_payroll_payments_match"),
        CheckConstraint(schema.CK_PAYMENT_MATCHED, name="ck_payroll_payments_matched"),
        CheckConstraint(
            schema.CK_PAYMENT_CURRENCY, name="ck_payroll_payments_currency"
        ),
        CheckConstraint(schema.CK_PAYMENT_AMOUNT, name="ck_payroll_payments_amount"),
        CheckConstraint(schema.CK_PAYMENT_BATCH, name="ck_payroll_payments_batch"),
        CheckConstraint(
            schema.CK_PAYMENT_STATEMENT, name="ck_payroll_payments_statement"
        ),
        CheckConstraint(schema.CK_PAYMENT_MANUAL, name="ck_payroll_payments_manual"),
        CheckConstraint(schema.CK_PAYMENT_TITLE, name="ck_payroll_payments_title"),
        CheckConstraint(schema.CK_PAYMENT_LAST4, name="ck_payroll_payments_last4"),
        Index(
            "uq_payroll_payments_statement_line",
            "statement_sha256",
            "statement_line_ref",
            unique=True,
            postgresql_where=text(schema.STATEMENT_LINE_WHERE),
        ),
        Index("ix_payroll_payments_settlement", "settlement_id"),
        Index(
            "ix_payroll_payments_batch",
            "batch_key",
            postgresql_where=text("batch_key IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    settlement_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("payroll_settlements.id", ondelete="SET NULL"), nullable=True
    )
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
    counterparty_last4: Mapped[Optional[str]] = mapped_column(
        String(4), nullable=True
    )
    batch_key: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    batch_format: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    statement_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    statement_format: Mapped[Optional[str]] = mapped_column(String(8), nullable=True)
    statement_line_ref: Mapped[Optional[str]] = mapped_column(
        String(64), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(
        String(schema.REASON_MAX_LENGTH), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
