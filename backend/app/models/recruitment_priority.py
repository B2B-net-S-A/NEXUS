"""Persistence primitives for Recruitment Priority Lock.

The priority plan controls *opening* new candidate/job processes.  It is kept
separate from ``Job.priority``, ownership and collaborator membership so those
legacy concepts cannot accidentally grant sourcing permission.

Published plans are immutable at the service layer.  Database constraints keep
the most important cross-request invariants true even when a future writer
forgets to validate them:

* at most one published plan,
* at most one active demand per job,
* one numeric position and one job per plan member,
* explicit reasons for Competence Category exceptions,
* a single persisted worker-state row.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
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


class PriorityMode(str, enum.Enum):
    off = "off"
    shadow = "shadow"
    enforce = "enforce"


class PriorityPlanStatus(str, enum.Enum):
    draft = "draft"
    published = "published"
    superseded = "superseded"


class PriorityMemberStatus(str, enum.Enum):
    active = "active"
    paused = "paused"


class PriorityDemandStatus(str, enum.Enum):
    open = "open"
    covered = "covered"
    fulfilled = "fulfilled"
    paused = "paused"
    cancelled = "cancelled"


class PriorityRank(str, enum.Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"


def legacy_priority_rank(position: int) -> Optional[PriorityRank]:
    """A–E remains a wire alias for the first five positions."""
    return PriorityRank(chr(64 + position)) if 1 <= position <= 5 else None


def assignment_position(assignment: Any) -> int:
    position = getattr(assignment, "position", None)
    if position is not None:
        return int(position)
    rank = getattr(assignment, "rank", None)
    return ord(str(getattr(rank, "value", rank))) - 64 if rank else 1


def _legacy_position_default(context) -> int:
    rank = context.get_current_parameters().get("rank")
    return ord(str(getattr(rank, "value", rank))) - 64 if rank else 1


class PriorityChannel(str, enum.Enum):
    database = "database"
    linkedin = "linkedin"
    mixed = "mixed"


class PriorityBlockerCategory(str, enum.Enum):
    brief = "brief"
    client_feedback = "client_feedback"
    rate = "rate"
    market = "market"
    competence = "competence"
    capacity = "capacity"
    access = "access"
    other = "other"


class PriorityBlockerStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    resolved = "resolved"


class PriorityExceptionStatus(str, enum.Enum):
    approved = "approved"
    consumed = "consumed"
    revoked = "revoked"
    expired = "expired"


class PriorityAlertSeverity(str, enum.Enum):
    info = "info"
    warning = "warning"
    critical = "critical"


class PriorityOriginKind(str, enum.Enum):
    """How a canonical recruitment process entered Priority Work."""

    legacy = "legacy"
    assigned = "assigned"
    shadow_violation = "shadow_violation"
    external_inbound = "external_inbound"
    external_observed = "external_observed"
    manager_inbound = "manager_inbound"
    approved_exception = "approved_exception"


class RecruitmentPriorityPlan(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_plans"
    __table_args__ = (
        CheckConstraint("version > 0", name="ck_priority_plan_version_positive"),
        CheckConstraint(
            "row_version > 0", name="ck_priority_plan_row_version_positive"
        ),
        Index(
            "ux_recruitment_priority_one_published",
            "status",
            unique=True,
            postgresql_where=text("status = 'published'"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, unique=True)
    status: Mapped[PriorityPlanStatus] = mapped_column(
        Enum(PriorityPlanStatus, name="priorityplanstatus"),
        nullable=False,
        default=PriorityPlanStatus.draft,
        server_default=PriorityPlanStatus.draft.value,
        index=True,
    )
    previous_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    effective_from: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    review_due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    previous_plan = relationship(
        "RecruitmentPriorityPlan", remote_side="RecruitmentPriorityPlan.id"
    )
    members = relationship(
        "RecruitmentPriorityPlanMember",
        back_populates="plan",
        cascade="all, delete-orphan",
    )


class RecruitmentPriorityPlanMember(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_plan_members"
    __table_args__ = (
        UniqueConstraint("plan_id", "user_id", name="uq_priority_plan_member_user"),
        CheckConstraint(
            "verification_capacity >= 0",
            name="ck_priority_member_capacity_nonnegative",
        ),
        CheckConstraint(
            "status <> 'paused' OR NULLIF(btrim(paused_reason), '') IS NOT NULL",
            name="ck_priority_member_paused_reason",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_priority_plans.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    status: Mapped[PriorityMemberStatus] = mapped_column(
        Enum(PriorityMemberStatus, name="prioritymemberstatus"),
        nullable=False,
        default=PriorityMemberStatus.active,
        server_default=PriorityMemberStatus.active.value,
    )
    verification_capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=12, server_default="12"
    )
    capacity_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    paused_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    plan = relationship("RecruitmentPriorityPlan", back_populates="members")
    user = relationship("User", foreign_keys=[user_id])
    assignments = relationship(
        "RecruitmentPriorityAssignment",
        back_populates="plan_member",
        cascade="all, delete-orphan",
        order_by="RecruitmentPriorityAssignment.position",
    )


class RecruitmentPriorityDemand(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_demands"
    __table_args__ = (
        CheckConstraint(
            "expected_recommendations >= 3",
            name="ck_priority_demand_recommendations_minimum",
        ),
        CheckConstraint(
            "row_version > 0", name="ck_priority_demand_row_version_positive"
        ),
        Index(
            "ux_recruitment_priority_one_active_demand_per_job",
            "job_id",
            unique=True,
            postgresql_where=text("status IN ('open', 'covered', 'paused')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    requested_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[PriorityDemandStatus] = mapped_column(
        Enum(PriorityDemandStatus, name="prioritydemandstatus"),
        nullable=False,
        default=PriorityDemandStatus.open,
        server_default=PriorityDemandStatus.open.value,
        index=True,
    )
    proposed_rank: Mapped[Optional[PriorityRank]] = mapped_column(
        Enum(PriorityRank, name="priorityrank"), nullable=True
    )
    expected_recommendations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=3, server_default="3"
    )
    due_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    required_channel: Mapped[Optional[PriorityChannel]] = mapped_column(
        Enum(PriorityChannel, name="prioritychannel"), nullable=True
    )
    rationale: Mapped[str] = mapped_column(Text, nullable=False)
    brief_ready: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )

    job = relationship("Job", foreign_keys=[job_id])
    requested_by = relationship("User", foreign_keys=[requested_by_user_id])
    assignments = relationship("RecruitmentPriorityAssignment", back_populates="demand")


class RecruitmentPriorityAssignment(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_assignments"
    __table_args__ = (
        UniqueConstraint(
            "plan_member_id",
            "position",
            name="uq_priority_assignment_member_position",
            deferrable=True,
            initially="DEFERRED",
        ),
        CheckConstraint(
            "position > 0", name="ck_priority_assignment_position_positive"
        ),
        UniqueConstraint(
            "plan_member_id",
            "rank",
            name="uq_priority_assignment_member_rank",
        ),
        UniqueConstraint(
            "plan_member_id",
            "job_id",
            name="uq_priority_assignment_member_job",
        ),
        CheckConstraint(
            "verification_target >= 0",
            name="ck_priority_assignment_verifications_nonnegative",
        ),
        CheckConstraint(
            "recommendation_target >= 0",
            name="ck_priority_assignment_recommendations_nonnegative",
        ),
        CheckConstraint(
            "competence_matches OR NULLIF(btrim(cc_exception_reason), '') IS NOT NULL",
            name="ck_priority_assignment_cc_exception_reason",
        ),
        Index("ix_priority_assignment_job", "job_id"),
        Index("ix_priority_assignment_demand", "demand_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_member_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_priority_plan_members.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    demand_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_priority_demands.id", ondelete="RESTRICT"),
        nullable=False,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=_legacy_position_default
    )
    rank: Mapped[Optional[PriorityRank]] = mapped_column(
        Enum(PriorityRank, name="priorityrank", create_type=False), nullable=True
    )
    channel: Mapped[PriorityChannel] = mapped_column(
        Enum(PriorityChannel, name="prioritychannel", create_type=False),
        nullable=False,
    )
    verification_target: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    recommendation_target: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    competence_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="SET NULL"), nullable=True
    )
    competence_matches: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    cc_exception_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    extra_slot_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    suggestion_source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="manual", server_default="manual"
    )

    plan_member = relationship(
        "RecruitmentPriorityPlanMember", back_populates="assignments"
    )
    demand = relationship("RecruitmentPriorityDemand", back_populates="assignments")
    job = relationship("Job", foreign_keys=[job_id])
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )
    blockers = relationship(
        "RecruitmentPriorityBlocker",
        back_populates="assignment",
        cascade="all, delete-orphan",
    )


class RecruitmentPriorityBlocker(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_blockers"
    __table_args__ = (
        CheckConstraint(
            "status NOT IN ('accepted', 'rejected') OR decided_at IS NOT NULL",
            name="ck_priority_blocker_decision_timestamp",
        ),
        CheckConstraint(
            "status <> 'resolved' OR resolved_at IS NOT NULL",
            name="ck_priority_blocker_resolved_at",
        ),
        Index(
            "ux_priority_blocker_assignment_active",
            "assignment_id",
            unique=True,
            postgresql_where=text(
                "status IN ('pending', 'accepted') AND resolved_at IS NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    assignment_id: Mapped[int] = mapped_column(
        ForeignKey("recruitment_priority_assignments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    reported_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    category: Mapped[PriorityBlockerCategory] = mapped_column(
        Enum(PriorityBlockerCategory, name="priorityblockercategory"),
        nullable=False,
    )
    description: Mapped[str] = mapped_column(Text, nullable=False)
    evidence: Mapped[Optional[dict[str, Any]]] = mapped_column(JSONB, nullable=True)
    status: Mapped[PriorityBlockerStatus] = mapped_column(
        Enum(PriorityBlockerStatus, name="priorityblockerstatus"),
        nullable=False,
        default=PriorityBlockerStatus.pending,
        server_default=PriorityBlockerStatus.pending.value,
        index=True,
    )
    decided_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    decision_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    resolved_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    assignment = relationship(
        "RecruitmentPriorityAssignment", back_populates="blockers"
    )


class RecruitmentPriorityException(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_exceptions"
    __table_args__ = (
        CheckConstraint(
            "expires_at > valid_from", name="ck_priority_exception_valid_window"
        ),
        CheckConstraint(
            "status <> 'consumed' OR consumed_at IS NOT NULL",
            name="ck_priority_exception_consumed_at",
        ),
        Index(
            "ux_priority_exception_one_approved_per_user_job",
            "user_id",
            "job_id",
            unique=True,
            postgresql_where=text("status = 'approved'"),
        ),
        Index("ix_priority_exception_expiry", "status", "expires_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    granted_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    origin_assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[PriorityExceptionStatus] = mapped_column(
        Enum(PriorityExceptionStatus, name="priorityexceptionstatus"),
        nullable=False,
        default=PriorityExceptionStatus.approved,
        server_default=PriorityExceptionStatus.approved.value,
        index=True,
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    consumed_candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True
    )
    consumed_process_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_processes.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )


class RecruitmentPriorityState(Base, TimestampMixin):
    __tablename__ = "recruitment_priority_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_recruitment_priority_state_singleton"),
        CheckConstraint(
            "row_version > 0", name="ck_priority_state_row_version_positive"
        ),
    )

    id: Mapped[int] = mapped_column(
        SmallInteger, primary_key=True, default=1, server_default="1"
    )
    current_plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_plans.id", ondelete="SET NULL"),
        nullable=True,
        unique=True,
    )
    row_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    worker_heartbeat_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_reconciled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_alert_sweep_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    metrics: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )

    current_plan = relationship(
        "RecruitmentPriorityPlan", foreign_keys=[current_plan_id]
    )


class RecruitmentPriorityAlert(Base, TimestampMixin):
    """Persisted, restart-safe alert deduplication record."""

    __tablename__ = "recruitment_priority_alerts"
    __table_args__ = (
        CheckConstraint(
            "occurrence_count > 0",
            name="ck_priority_alert_occurrence_count_positive",
        ),
        CheckConstraint(
            "last_seen_at >= first_seen_at",
            name="ck_priority_alert_seen_window",
        ),
        Index(
            "ix_priority_alert_unresolved",
            "severity",
            "last_seen_at",
            postgresql_where=text("resolved_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    dedupe_key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    severity: Mapped[PriorityAlertSeverity] = mapped_column(
        Enum(PriorityAlertSeverity, name="priorityalertseverity"),
        nullable=False,
        default=PriorityAlertSeverity.warning,
        server_default=PriorityAlertSeverity.warning.value,
    )
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_assignments.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurrence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class RecruitmentPriorityAuditEvent(Base):
    """Append-only evidence for privileged Priority Work decisions."""

    __tablename__ = "recruitment_priority_audit_events"
    __table_args__ = (
        Index(
            "ix_priority_audit_event_type_occurred",
            "event_type",
            "occurred_at",
        ),
        Index("ix_priority_audit_plan_occurred", "plan_id", "occurred_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    event_type: Mapped[str] = mapped_column(String(80), nullable=False)
    actor_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    plan_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_plans.id", ondelete="SET NULL"),
        nullable=True,
    )
    subject_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    assignment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_assignments.id", ondelete="SET NULL"),
        nullable=True,
    )
    process_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_processes.id", ondelete="SET NULL"), nullable=True
    )
    exception_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("recruitment_priority_exceptions.id", ondelete="SET NULL"),
        nullable=True,
    )
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb")
    )
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    correlation_id: Mapped[Optional[str]] = mapped_column(
        String(100), nullable=True, index=True
    )


class RecruitmentPriorityUserMode(Base, TimestampMixin):
    """Optional per-user ceiling used for cohort rollout.

    No row means the global ``RECRUITMENT_PRIORITY_MODE`` applies.  Services
    must never let a user row make enforcement stronger than the global mode.
    """

    __tablename__ = "recruitment_priority_user_modes"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    mode: Mapped[PriorityMode] = mapped_column(
        Enum(PriorityMode, name="prioritymode"),
        nullable=False,
        default=PriorityMode.off,
        server_default=PriorityMode.off.value,
    )
    set_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    effective_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
