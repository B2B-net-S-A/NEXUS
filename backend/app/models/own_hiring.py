"""Rekrutacja własna: tabele poza modelem zwykłych rekrutacji."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class OwnHiringProcess(Base):
    __tablename__ = "own_hiring_processes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(160), nullable=False)
    owner_user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    assistant_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    ad_titles: Mapped[list] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    settings: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    intake_since: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    intake_cursor: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
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


class OwnHiringApplication(Base):
    __tablename__ = "own_hiring_applications"
    __table_args__ = (
        UniqueConstraint(
            "process_id", "candidate_id", name="uq_own_hiring_application"
        ),
        Index(
            "uq_own_hiring_token",
            "token_sha256",
            unique=True,
            postgresql_where=text("token_sha256 IS NOT NULL"),
        ),
        Index("ix_own_hiring_app_board", "process_id", "stage", "bucket"),
        Index("ix_own_hiring_app_candidate", "candidate_id"),
        Index(
            "ix_own_hiring_app_due",
            "response_due_at",
            postgresql_where=text("stage = 'invited'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("own_hiring_processes.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    stage: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default=text("'new'")
    )
    bucket: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'review'")
    )
    filter_reason: Mapped[Optional[str]] = mapped_column(String(20))
    evidence: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    source_label: Mapped[Optional[str]] = mapped_column(String(80))
    ad_title: Mapped[Optional[str]] = mapped_column(String(300))
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    stage_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    token_nonce: Mapped[Optional[str]] = mapped_column(String(32))
    token_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    invited_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    response_due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    replied_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    handed_off_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    call_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    callback_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    availability: Mapped[Optional[str]] = mapped_column(String(20))
    expected_money: Mapped[Optional[str]] = mapped_column(String(160))
    tech_level: Mapped[Optional[str]] = mapped_column(String(20))
    teams_note: Mapped[Optional[str]] = mapped_column(Text)
    office_note: Mapped[Optional[str]] = mapped_column(Text)
    contract_kind: Mapped[Optional[str]] = mapped_column(String(20))
    contract_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    close_reason: Mapped[Optional[str]] = mapped_column(String(20))
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class OwnHiringBooking(Base):
    __tablename__ = "own_hiring_bookings"
    __table_args__ = (
        Index(
            "uq_own_hiring_active_slot",
            "process_id",
            "start_at",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("ix_own_hiring_booking_app", "application_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    process_id: Mapped[int] = mapped_column(
        ForeignKey("own_hiring_processes.id", ondelete="CASCADE"), nullable=False
    )
    application_id: Mapped[int] = mapped_column(
        ForeignKey("own_hiring_applications.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'active'")
    )
    booked_via: Mapped[str] = mapped_column(String(10), nullable=False)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    graph_event_id: Mapped[Optional[str]] = mapped_column(String(255))
    join_url: Mapped[Optional[str]] = mapped_column(Text)
    sync_status: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default=text("'pending'")
    )
    sync_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0")
    )
    reminder_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
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


class OwnHiringEvent(Base):
    __tablename__ = "own_hiring_events"
    __table_args__ = (
        Index("ix_own_hiring_events_app", "application_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(
        ForeignKey("own_hiring_applications.id", ondelete="CASCADE"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
