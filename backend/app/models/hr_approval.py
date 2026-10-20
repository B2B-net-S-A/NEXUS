"""„Ludzie w NEXUSIE” — model: zgoda na wydatek albo premię poza umową (0483).

CHECK-i i indeksy muszą być identyczne z ``app/services/hr_approvals_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
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
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
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
