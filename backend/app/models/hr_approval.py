"""„Ludzie w NEXUSIE” — model: zgoda na wydatek albo premię poza umową (0483).

CHECK-i i indeksy muszą być identyczne z ``app/services/hr_approvals_schema.py``
i ``app/services/hr_approval_settlement_schema.py`` (0485 — rozliczenie
w Finansach; strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
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
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_approval_settlement_schema as settlement
from app.services import hr_approvals_schema as schema


class ApprovalRequest(TimestampMixin, Base):
    __tablename__ = "approval_requests"
    __table_args__ = (
        CheckConstraint(schema.CK_KIND, name="ck_approval_requests_kind"),
        CheckConstraint(schema.CK_STATUS, name="ck_approval_requests_status"),
        CheckConstraint(schema.CK_RECURRENCE, name="ck_approval_requests_recurrence"),
        CheckConstraint(schema.CK_BASIS, name="ck_approval_requests_basis"),
        CheckConstraint(schema.CK_PAYER, name="ck_approval_requests_payer"),
        CheckConstraint(schema.CK_CURRENCY, name="ck_approval_requests_currency"),
        CheckConstraint(schema.CK_AMOUNT, name="ck_approval_requests_amount"),
        CheckConstraint(
            schema.CK_DECIDED_AMOUNT, name="ck_approval_requests_decided_amount"
        ),
        CheckConstraint(schema.CK_CHANNEL, name="ck_approval_requests_channel"),
        CheckConstraint(schema.CK_BONUS_SHAPE, name="ck_approval_requests_bonus_shape"),
        CheckConstraint(
            schema.CK_NOT_FOR_SELF, name="ck_approval_requests_not_for_self"
        ),
        CheckConstraint(
            schema.CK_NOT_OWN_DECISION, name="ck_approval_requests_not_own_decision"
        ),
        CheckConstraint(
            schema.CK_NOT_OWN_ENDORSEMENT,
            name="ck_approval_requests_not_own_endorsement",
        ),
        CheckConstraint(schema.CK_DECIDED, name="ck_approval_requests_decided"),
        CheckConstraint(
            schema.CK_SUPERVISOR_STEP, name="ck_approval_requests_supervisor_step"
        ),
        Index("ix_approval_requests_requester", "requester_user_id", "submitted_at"),
        Index(
            "ix_approval_requests_pending",
            "status",
            "supervisor_user_id",
            postgresql_where=text(schema.PENDING_WHERE),
        ),
        Index(
            "ix_approval_requests_decided",
            "kind",
            "decided_at",
            postgresql_where=text(schema.APPROVED_WHERE),
        ),
        CheckConstraint(
            settlement.CK_REQ_SETTLEMENT, name="ck_approval_requests_settlement"
        ),
        CheckConstraint(settlement.CK_REQ_CLIENT, name="ck_approval_requests_client"),
        CheckConstraint(
            settlement.CK_REQ_SELLER_NIP, name="ck_approval_requests_seller_nip"
        ),
        Index(
            "ix_approval_requests_settlement",
            "settlement_status",
            "kind",
            postgresql_where=text(settlement.SETTLEMENT_WHERE),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(schema.TITLE_MAX_LENGTH), nullable=False)
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    amount_basis: Mapped[str] = mapped_column(
        String(5), nullable=False, default="gross", server_default="gross"
    )
    recurrence: Mapped[str] = mapped_column(
        String(10), nullable=False, default="once", server_default="once"
    )
    payer: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    link_url: Mapped[Optional[str]] = mapped_column(
        String(schema.LINK_MAX_LENGTH), nullable=True
    )
    needed_by: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    starts_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ends_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    beneficiary_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    payout_year: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    payout_month: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    requester_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    supervisor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    needs_final: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    endorsed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    endorsed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    endorse_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decided_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    decision_channel: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    bonus_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("hr_bonuses.id", ondelete="SET NULL"), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 0485 — rozliczenie w Finansach.
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    seller_nip: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    settlement_status: Mapped[Optional[str]] = mapped_column(String(12), nullable=True)
    expires_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    settled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    renews_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    renewal_asked_for: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    renewal_confirmed_for: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ended_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    ended_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ApprovalDocument(Base):
    """Faktura albo paragon do zgody (``upload``) albo faktura kosztowa z KSeF."""

    __tablename__ = "approval_documents"
    __table_args__ = (
        CheckConstraint(settlement.CK_DOC_SOURCE, name="ck_approval_documents_source"),
        CheckConstraint(settlement.CK_DOC_TYPE, name="ck_approval_documents_type"),
        CheckConstraint(settlement.CK_DOC_STATUS, name="ck_approval_documents_status"),
        CheckConstraint(settlement.CK_DOC_ORIGIN, name="ck_approval_documents_origin"),
        CheckConstraint(
            settlement.CK_DOC_ATTACHED, name="ck_approval_documents_attached"
        ),
        CheckConstraint(
            settlement.CK_DOC_SELLER_NIP, name="ck_approval_documents_seller_nip"
        ),
        CheckConstraint(
            settlement.CK_DOC_CURRENCY, name="ck_approval_documents_currency"
        ),
        CheckConstraint(settlement.CK_DOC_READ, name="ck_approval_documents_read"),
        CheckConstraint(settlement.CK_DOC_TOPUP, name="ck_approval_documents_topup"),
        CheckConstraint(
            settlement.CK_DOC_TOPUP_DECIDED,
            name="ck_approval_documents_topup_decided",
        ),
        CheckConstraint(
            settlement.CK_DOC_SETTLED, name="ck_approval_documents_settled"
        ),
        Index(
            "uq_approval_documents_ksef_number",
            "ksef_number",
            unique=True,
            postgresql_where=text(settlement.KSEF_WHERE),
        ),
        Index(
            "uq_approval_documents_request_file",
            "approval_request_id",
            "sha256",
            unique=True,
            postgresql_where=text(settlement.SHA_WHERE),
        ),
        Index(
            "ix_approval_documents_request",
            "approval_request_id",
            postgresql_where=text(settlement.ATTACHED_WHERE),
        ),
        Index(
            "ix_approval_documents_queue",
            "issue_date",
            postgresql_where=text(settlement.QUEUE_WHERE),
        ),
        Index("ix_approval_documents_seller", "seller_nip"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(8), nullable=False)
    doc_type: Mapped[str] = mapped_column(
        String(10), nullable=False, default="invoice", server_default="invoice"
    )
    status: Mapped[str] = mapped_column(String(12), nullable=False)
    approval_request_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("approval_requests.id", ondelete="SET NULL"), nullable=True
    )
    match_reason: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    ksef_number: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    ksef_invoice_type: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    seller_nip: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    seller_name: Mapped[Optional[str]] = mapped_column(
        String(settlement.SELLER_NAME_MAX_LENGTH), nullable=True
    )
    invoice_number: Mapped[Optional[str]] = mapped_column(
        String(settlement.INVOICE_NUMBER_MAX_LENGTH), nullable=True
    )
    issue_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    net_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    vat_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(14, 2), nullable=True)
    gross_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    file_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    mime: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    size_bytes: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    read_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    read_result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    topup_status: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    topup_amount: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(14, 2), nullable=True
    )
    topup_requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    topup_requested_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    topup_decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    topup_decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    topup_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    settled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    settled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    settle_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    close_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    fetched_at: Mapped[Optional[datetime]] = mapped_column(
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


class ApprovalFixedCostSeller(Base):
    """Sprzedawca, którego faktury nie wymagają zgody („stały koszt”)."""

    __tablename__ = "approval_fixed_cost_sellers"
    __table_args__ = (
        CheckConstraint(
            "seller_nip ~ '^[0-9]{10}$'", name="ck_approval_fixed_cost_sellers_nip"
        ),
    )

    seller_nip: Mapped[str] = mapped_column(String(10), primary_key=True)
    seller_name: Mapped[Optional[str]] = mapped_column(
        String(settlement.SELLER_NAME_MAX_LENGTH), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
