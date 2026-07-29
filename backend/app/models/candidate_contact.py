"""Durable coordination state for candidate-first telephone outreach.

Pipeline/shortlist membership remains per recruitment.  The models in this
module add the orthogonal, candidate-global answer to "who is calling this
person next?".  Statuses deliberately use VARCHAR columns: Python enums and
Pydantic validate application writes without introducing PostgreSQL enum
types, which keeps the migration additive and safe for the production
``create_all`` fallback.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class _ValueEnum(str, enum.Enum):
    def __str__(self) -> str:
        return self.value


class CandidateContactState(_ValueEnum):
    unassigned = "unassigned"
    awaiting_capacity = "awaiting_capacity"
    queued = "queued"
    callback_due = "callback_due"
    cooldown = "cooldown"
    handoff_pending = "handoff_pending"
    blocked_no_phone = "blocked_no_phone"
    suppressed = "suppressed"
    completed = "completed"
    cancelled = "cancelled"


class CandidateContactOutcome(_ValueEnum):
    connected = "connected"
    no_answer = "no_answer"
    callback_requested = "callback_requested"
    wrong_number = "wrong_number"
    do_not_contact = "do_not_contact"


class CandidateContactOpportunityOutcome(_ValueEnum):
    interested = "interested"
    maybe = "maybe"
    not_interested = "not_interested"
    not_presented = "not_presented"


class CandidateContactOpportunitySource(_ValueEnum):
    pipeline = "pipeline"
    shortlist = "shortlist"
    traffit = "traffit"
    manual = "manual"


class CandidateContactEventType(_ValueEnum):
    case_created = "case_created"
    opportunity_added = "opportunity_added"
    opportunity_closed = "opportunity_closed"
    assigned = "assigned"
    reassigned = "reassigned"
    awaiting_capacity = "awaiting_capacity"
    attempt_logged = "attempt_logged"
    opportunity_outcome_recorded = "opportunity_outcome_recorded"
    cooldown_started = "cooldown_started"
    cooldown_ended = "cooldown_ended"
    phone_blocked = "phone_blocked"
    phone_restored = "phone_restored"
    handoff_scheduled = "handoff_scheduled"
    handoff_cancelled = "handoff_cancelled"
    case_completed = "case_completed"
    case_reopened = "case_reopened"
    suppressed = "suppressed"


CONTACT_CASE_STATES = tuple(state.value for state in CandidateContactState)
CONTACT_OUTCOMES = tuple(outcome.value for outcome in CandidateContactOutcome)
CONTACT_OPPORTUNITY_OUTCOMES = tuple(
    outcome.value for outcome in CandidateContactOpportunityOutcome
)
CONTACT_OPPORTUNITY_SOURCES = tuple(
    source.value for source in CandidateContactOpportunitySource
)
QUEUE_STATES = (
    CandidateContactState.queued.value,
    CandidateContactState.callback_due.value,
)


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class CandidateContactCase(Base, TimestampMixin):
    """One current contact-coordination case per canonical candidate."""

    __tablename__ = "candidate_contact_cases"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", name="uq_candidate_contact_cases_candidate_id"
        ),
        CheckConstraint(
            f"state IN ({_sql_values(CONTACT_CASE_STATES)})",
            name="ck_candidate_contact_cases_state",
        ),
        CheckConstraint(
            "queue_slot IS NULL OR (queue_slot BETWEEN 1 AND 20)",
            name="ck_candidate_contact_cases_queue_slot",
        ),
        CheckConstraint(
            "queue_slot IS NULL OR owner_user_id IS NOT NULL",
            name="ck_candidate_contact_cases_slot_owner",
        ),
        CheckConstraint(
            "(state IN ('queued', 'callback_due')) = (queue_slot IS NOT NULL)",
            name="ck_candidate_contact_cases_actionable_slot",
        ),
        CheckConstraint(
            "attempt_count >= 0", name="ck_candidate_contact_cases_attempt_count"
        ),
        CheckConstraint("cycle >= 1", name="ck_candidate_contact_cases_cycle"),
        CheckConstraint("version >= 1", name="ck_candidate_contact_cases_version"),
        Index(
            "ux_candidate_contact_cases_owner_slot",
            "owner_user_id",
            "queue_slot",
            unique=True,
            postgresql_where=text("queue_slot IS NOT NULL"),
        ),
        Index(
            "ix_candidate_contact_cases_state_due",
            "state",
            "due_at",
        ),
        Index(
            "ix_candidate_contact_cases_owner_state",
            "owner_user_id",
            "state",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    previous_owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    primary_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )

    state: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CandidateContactState.unassigned.value,
        server_default=CandidateContactState.unassigned.value,
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Consecutive unanswered dials in the current cycle, not all Call rows.
    attempt_count: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default="0"
    )
    cycle: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    queue_slot: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)

    assigned_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # ``wrong_number`` stores the rejected value; the worker only reopens when
    # the candidate has a different, non-empty phone number.
    blocked_phone_value: Mapped[Optional[str]] = mapped_column(String(30))

    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    owner = relationship("User", foreign_keys=[owner_user_id])
    previous_owner = relationship("User", foreign_keys=[previous_owner_user_id])
    primary_job = relationship("Job", foreign_keys=[primary_job_id])
    opportunities = relationship(
        "CandidateContactOpportunity",
        back_populates="case",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    calls = relationship(
        "Call",
        back_populates="contact_case",
        passive_deletes=True,
    )


class CandidateContactOpportunity(Base, TimestampMixin):
    """One recruitment that may be discussed within a global contact case."""

    __tablename__ = "candidate_contact_opportunities"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "job_id",
            name="uq_candidate_contact_opportunities_candidate_job",
        ),
        UniqueConstraint(
            "case_id",
            "job_id",
            name="uq_candidate_contact_opportunities_case_job",
        ),
        CheckConstraint(
            f"source IN ({_sql_values(CONTACT_OPPORTUNITY_SOURCES)})",
            name="ck_candidate_contact_opportunities_source",
        ),
        CheckConstraint(
            "outcome IS NULL OR "
            f"outcome IN ({_sql_values(CONTACT_OPPORTUNITY_OUTCOMES)})",
            name="ck_candidate_contact_opportunities_outcome",
        ),
        Index(
            "ix_candidate_contact_opportunities_case_open",
            "case_id",
            "closed_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    case_id: Mapped[int] = mapped_column(
        ForeignKey("candidate_contact_cases.id", ondelete="CASCADE"),
        nullable=False,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Deliberately denormalized, like the immutable event's job_id.  The job
    # delete hook closes this row first, and the tombstone must survive the
    # physical Job DELETE so source/outcome history is not erased by CASCADE.
    # Domain ingress validates that the Job exists before creating a row.
    job_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    source: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default=CandidateContactOpportunitySource.manual.value,
        server_default=CandidateContactOpportunitySource.manual.value,
    )
    source_external_ref: Mapped[Optional[str]] = mapped_column(String(255))
    # Source event time, not ingestion time. Late/batch Traffit rows must keep
    # the same priority ordering they had when linked in the source system.
    linked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Latest applied Traffit tuple.  This is intentionally separate from
    # linked_at: owner selection uses the oldest link, while equal-second
    # source events need (created_at, external_id) ordering for stale retries.
    source_cursor_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    source_cursor_external_id: Mapped[Optional[str]] = mapped_column(String(255))
    outcome: Mapped[Optional[str]] = mapped_column(String(32))
    presented_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    meeting_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True
    )
    meeting_scheduled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    closed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    closed_reason: Mapped[Optional[str]] = mapped_column(String(64))

    case = relationship("CandidateContactCase", back_populates="opportunities")
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    meeting_event = relationship("CalendarEvent", foreign_keys=[meeting_event_id])


class CandidateContactEvent(Base):
    """Append-only state/audit event.

    Writers only INSERT.  Corrections are represented by a new event, never by
    editing old evidence.
    """

    __tablename__ = "candidate_contact_events"
    __table_args__ = (
        Index(
            "ux_candidate_contact_events_idempotency",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_candidate_contact_events_case_occurred",
            "case_id",
            "occurred_at",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    # Deliberately denormalized IDs without FKs. The immutable audit must
    # survive candidate/job/case deletion; FK cascades or SET NULL actions
    # would either erase evidence or collide with the mutation-blocking trigger.
    case_id: Mapped[int] = mapped_column(Integer, nullable=False)
    candidate_id: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    opportunity_id: Mapped[Optional[int]] = mapped_column(Integer)
    job_id: Mapped[Optional[int]] = mapped_column(Integer)
    actor_user_id: Mapped[Optional[int]] = mapped_column(Integer)
    call_id: Mapped[Optional[int]] = mapped_column(Integer)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    from_state: Mapped[Optional[str]] = mapped_column(String(32))
    to_state: Mapped[Optional[str]] = mapped_column(String(32))
    idempotency_key: Mapped[Optional[str]] = mapped_column(String(160))
    details: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class CandidateContactTraffitCursor(Base, TimestampMixin):
    """Restart-safe `(created_at, external_id)` cursor for read-only intake."""

    __tablename__ = "candidate_contact_traffit_cursors"

    stream: Mapped[str] = mapped_column(String(64), primary_key=True)
    cursor_created_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    cursor_external_id: Mapped[Optional[str]] = mapped_column(String(255))
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    last_success_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    status: Mapped[Optional[str]] = mapped_column(String(32))
    last_error: Mapped[Optional[str]] = mapped_column(Text)


class CandidateContactTraffitLedger(Base, TimestampMixin):
    """Deduplication and exception ledger for Traffit recruitment_history."""

    __tablename__ = "candidate_contact_traffit_ledger"
    __table_args__ = (
        UniqueConstraint(
            "external_event_id",
            name="uq_candidate_contact_traffit_ledger_external_event",
        ),
        CheckConstraint(
            "status IN ('processed', 'exception')",
            name="ck_candidate_contact_traffit_ledger_status",
        ),
        CheckConstraint(
            "attempts >= 0",
            name="ck_candidate_contact_traffit_ledger_attempts",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    external_event_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    candidate_external_id: Mapped[Optional[str]] = mapped_column(String(255))
    job_external_id: Mapped[Optional[str]] = mapped_column(String(255))
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), index=True
    )
    case_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_contact_cases.id", ondelete="SET NULL")
    )
    opportunity_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_contact_opportunities.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_attempt_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    error: Mapped[Optional[str]] = mapped_column(Text)
    processed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
