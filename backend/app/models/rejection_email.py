"""Automatic rejection-notification emails to candidates.

One row per scheduled email. Created when a recruiter moves a candidate to
`rejected` AND the *previous* stage was one of the "client-visible" stages
(cv_sent, client_interview, acceptance, negotiation, onboarding). The
background loop `app.tasks.rejection_email_loop` picks up due rows and sends
them via `app.services.m365.sender.send_new()` from the recruiter's mailbox.

A 15-minute delay window lets the recruiter cancel ("undo") through
`POST /api/rejection-emails/{id}/cancel`. Body is snapshotted at schedule
time so template edits during the window don't affect the queued message.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class RejectionEmailStatus(str, enum.Enum):
    """Lifecycle of a scheduled rejection email."""

    pending = "pending"  # queued, awaiting scheduled_at
    sent = "sent"  # successfully dispatched via Graph
    cancelled = "cancelled"  # undo before dispatch
    failed = "failed"  # final failure after retry attempts
    skipped = "skipped"  # no M365 connection — nothing sent


class ScheduledRejectionEmail(Base, TimestampMixin):
    """Scheduled candidate-rejection email.

    Lives separate from `emails` because we need a row BEFORE the message
    exists in Graph (for the undo window). Links to `emails.id` via
    `email_id` once the dispatch succeeds.
    """

    __tablename__ = "scheduled_rejection_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # The rejection-move stage that triggered this email. Unique: at most one
    # scheduled email per stage move. CASCADE so DB stays clean if the stage
    # row is ever hard-deleted.
    candidate_stage_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Sender — mailbox owner whose M365 connection is used.
    recruiter_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Frozen snapshots — shield the queued message from later edits.
    to_email: Mapped[str] = mapped_column(String(320), nullable=False)
    subject: Mapped[str] = mapped_column(String(998), nullable=False)
    body_html: Mapped[str] = mapped_column(Text, nullable=False)
    # Shape: [{"job_id": int, "title": str}, ...]
    other_processes: Mapped[Optional[list]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )

    # Template used (informational — body is already rendered and stored).
    template_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("email_templates.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[RejectionEmailStatus] = mapped_column(
        Enum(RejectionEmailStatus, name="rejectionemailstatus"),
        default=RejectionEmailStatus.pending,
        nullable=False,
        index=True,
    )
    scheduled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancelled_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Populated after successful send — bridges to the main emails table.
    email_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL"), nullable=True
    )

    # Retry bookkeeping.
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    job = relationship("Job", foreign_keys=[job_id])
    candidate_stage = relationship("CandidateStage", foreign_keys=[candidate_stage_id])
    recruiter = relationship("User", foreign_keys=[recruiter_id])
    cancelled_by_user = relationship("User", foreign_keys=[cancelled_by])
    template = relationship("EmailTemplate", foreign_keys=[template_id])
    email = relationship("Email", foreign_keys=[email_id])

    __table_args__ = (
        # Partial index for the hot-path loop query:
        # WHERE status = 'pending' AND scheduled_at <= now()
        Index(
            "ix_scheduled_rejemail_pending_due",
            "status",
            "scheduled_at",
            postgresql_where=text("status = 'pending'"),
        ),
    )

    def __repr__(self) -> str:
        return (
            f"<ScheduledRejectionEmail id={self.id} candidate={self.candidate_id} "
            f"job={self.job_id} status={self.status} "
            f"scheduled_at={self.scheduled_at}>"
        )
