"""„Ludzie w NEXUSIE” — modele: Urlopy i zastępstwa (0458).

CHECK-i i indeksy muszą być identyczne z ``app/services/*_schema.py`` modułu
(strażnik dryfu schematu porównuje model z bazą po migracji).

* ``LeaveRequest`` — wniosek o nieobecność (id UUID zachowany z Compassa).
* ``LeaveRequestDay`` — dzień roboczy wniosku per wiersz; ``active`` mówi, czy
  wniosek oczekuje albo jest zatwierdzony, ``paid`` — czy dzień jest z puli
  płatnej. Zużycie puli i nakładki liczy się z tej tabeli, nie z zakresu dat.
* ``HrM365Operation`` — kolejka operacji Microsoft Graph (wykonuje ją pętla
  z kolejnego etapu; lokalnie tryb symulacji).
* ``HrM365MailboxState`` — stan skrzynki osoby.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Numeric,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin
from app.services import hr_leave_schema as schema


class LeaveRequest(Base, TimestampMixin):
    """Wniosek o nieobecność (urlop, L4, okolicznościowy…)."""

    __tablename__ = "leave_requests"
    __table_args__ = (
        CheckConstraint(schema.CK_LEAVE_TYPE, name="ck_leave_requests_type"),
        CheckConstraint(schema.CK_LEAVE_STATUS, name="ck_leave_requests_status"),
        CheckConstraint(schema.CK_LEAVE_DATES, name="ck_leave_requests_dates"),
        CheckConstraint(schema.CK_LEAVE_HALF_DAY, name="ck_leave_requests_half_day"),
        CheckConstraint(
            schema.CK_LEAVE_SUBSTITUTE, name="ck_leave_requests_substitute"
        ),
        CheckConstraint(
            schema.CK_LEAVE_FORWARD_CONSENT, name="ck_leave_requests_forward_consent"
        ),
        CheckConstraint(
            schema.CK_LEAVE_NO_SELF_DECISION, name="ck_leave_requests_no_self_decision"
        ),
        CheckConstraint(schema.CK_LEAVE_DAYS, name="ck_leave_requests_days"),
        CheckConstraint(schema.CK_LEAVE_SOURCE, name="ck_leave_requests_source"),
        Index("ix_leave_requests_user_start", "user_id", "start_date"),
        Index("ix_leave_requests_status_start", "status", "start_date"),
        Index("ix_leave_requests_substitute", "substitute_user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    leave_type: Mapped[str] = mapped_column(String(24), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    half_day: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    substitute_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    # Kto wrzuca do Cpro za osobę od Cpro w czasie tego urlopu (0618,
    # `cpro_sender.effective_sender`). Osobno od zastępcy akceptacji i poczty.
    cpro_substitute_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    forward_mail_consent: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    oof_internal_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    oof_external_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paid_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    unpaid_days: Mapped[Decimal] = mapped_column(
        Numeric(5, 1), nullable=False, default=Decimal("0"), server_default="0"
    )
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(
        String(16), nullable=False, default="self", server_default="self"
    )


class LeaveRequestDay(Base):
    """Dzień roboczy wniosku (1,0 albo 0,5 dnia)."""

    __tablename__ = "leave_request_days"
    __table_args__ = (
        UniqueConstraint(
            "leave_request_id", "day", name="uq_leave_request_days_request_day"
        ),
        CheckConstraint(schema.CK_DAY_FRACTION, name="ck_leave_request_days_fraction"),
        Index(
            "uq_leave_request_days_user_day_active",
            "user_id",
            "day",
            unique=True,
            postgresql_where=text(schema.ACTIVE_DAY_WHERE),
        ),
        Index("ix_leave_request_days_day", "day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    leave_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_requests.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    day: Mapped[date] = mapped_column(Date, nullable=False)
    fraction: Mapped[Decimal] = mapped_column(
        Numeric(2, 1), nullable=False, default=Decimal("1.0"), server_default="1.0"
    )
    paid: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )


class HrM365Operation(Base):
    """Operacja Microsoft Graph czekająca na wykonanie (albo symulację)."""

    __tablename__ = "hr_m365_operations"
    __table_args__ = (
        UniqueConstraint("dedupe_key", name="uq_hr_m365_operations_dedupe"),
        CheckConstraint(schema.CK_M365_KIND, name="ck_hr_m365_operations_kind"),
        CheckConstraint(schema.CK_M365_STATUS, name="ck_hr_m365_operations_status"),
        CheckConstraint(schema.CK_M365_ATTEMPTS, name="ck_hr_m365_operations_attempts"),
        Index("ix_hr_m365_operations_due", "status", "next_attempt_at"),
        Index("ix_hr_m365_operations_leave", "leave_request_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    leave_request_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("leave_requests.id", ondelete="SET NULL"),
        nullable=True,
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    dedupe_key: Mapped[str] = mapped_column(String(200), nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    next_attempt_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    simulated_request: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSONB, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    done_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class HrM365MailboxState(Base):
    """Stan skrzynki osoby po ostatnim uzgodnieniu z Microsoft 365."""

    __tablename__ = "hr_m365_mailbox_state"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    custom_oof_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    last_reconciled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    state: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
