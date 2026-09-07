"""Durable availability, allocation queue, and transaction-bound recalculation events."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class WorkforceAvailabilityState(Base):
    __tablename__ = "workforce_availability_state"
    __table_args__ = (CheckConstraint("id = 1", name="ck_workforce_singleton"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    snapshot: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(200))


class RecruitmentAllocationState(Base):
    __tablename__ = "recruitment_allocation_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_allocation_singleton"),
        CheckConstraint("mode IN ('off', 'shadow', 'auto')", name="ck_allocation_mode"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    mode: Mapped[str] = mapped_column(
        String(10), default="shadow", server_default="shadow"
    )
    last_run_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[Optional[str]] = mapped_column(String(200))
    stats: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)


class RecruitmentAllocationRequest(Base, TimestampMixin):
    __tablename__ = "recruitment_allocation_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'assigned', 'cancelled')",
            name="ck_allocation_request_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), unique=True
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    channel: Mapped[str] = mapped_column(
        String(20), default="linkedin", server_default="linkedin"
    )
    status: Mapped[str] = mapped_column(
        String(20), default="queued", server_default="queued", index=True
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    evaluated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    assigned_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    suggested_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    reason: Mapped[Optional[str]] = mapped_column(String(100))
    decision: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB)
    matching_snapshot_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("proposal_snapshots.id", ondelete="SET NULL")
    )
    matching_attempts: Mapped[int] = mapped_column(
        Integer, default=0, server_default="0"
    )
    matching_claimed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )


class RecruitmentAllocationEvent(Base):
    __tablename__ = "recruitment_allocation_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), index=True
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    last_error: Mapped[Optional[str]] = mapped_column(Text)
