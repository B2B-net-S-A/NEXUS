"""Pydantic contracts for Recruitment Priority Lock and carry-over work."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.models.recruitment_priority import (
    PriorityAlertSeverity,
    PriorityBlockerCategory,
    PriorityBlockerStatus,
    PriorityChannel,
    PriorityDemandStatus,
    PriorityExceptionStatus,
    PriorityMemberStatus,
    PriorityMode,
    PriorityOriginKind,
    PriorityPlanStatus,
    PriorityRank,
)

MAX_BLOCKER_EVIDENCE_BYTES = 16 * 1024


def validate_blocker_evidence(
    value: Optional[dict[str, Any]],
) -> Optional[dict[str, Any]]:
    """Keep blocker metadata JSON-safe and bounded before it reaches JSONB."""

    if value is None:
        return None
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("evidence must contain JSON-serializable values") from exc
    if len(encoded) > MAX_BLOCKER_EVIDENCE_BYTES:
        raise ValueError(
            f"evidence must be at most {MAX_BLOCKER_EVIDENCE_BYTES} UTF-8 bytes"
        )
    return value


class PrioritySchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PriorityDemandCreate(BaseModel):
    job_id: int = Field(gt=0)
    proposed_rank: Optional[PriorityRank] = None
    expected_recommendations: int = Field(default=3, ge=3)
    due_at: Optional[datetime] = None
    required_channel: Optional[PriorityChannel] = None
    rationale: str = Field(min_length=1, max_length=4000)
    brief_ready: bool = False


class PriorityDemandUpdate(BaseModel):
    expected_version: int = Field(gt=0)
    proposed_rank: Optional[PriorityRank] = None
    expected_recommendations: Optional[int] = Field(default=None, ge=3)
    due_at: Optional[datetime] = None
    required_channel: Optional[PriorityChannel] = None
    rationale: Optional[str] = Field(default=None, min_length=1, max_length=4000)
    brief_ready: Optional[bool] = None
    status: Optional[PriorityDemandStatus] = None


class PriorityDemandRead(PrioritySchema):
    id: int
    job_id: int
    requested_by_user_id: Optional[int]
    status: PriorityDemandStatus
    proposed_rank: Optional[PriorityRank]
    expected_recommendations: int
    due_at: Optional[datetime]
    required_channel: Optional[PriorityChannel]
    rationale: str
    brief_ready: bool
    row_version: int
    created_at: datetime
    updated_at: datetime


class PriorityAssignmentInput(BaseModel):
    demand_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    rank: PriorityRank
    channel: PriorityChannel
    verification_target: int = Field(default=0, ge=0)
    recommendation_target: int = Field(default=0, ge=0)
    competence_category_id: Optional[int] = Field(default=None, gt=0)
    competence_matches: bool = True
    cc_exception_reason: Optional[str] = Field(default=None, max_length=4000)
    extra_slot_reason: Optional[str] = Field(default=None, max_length=4000)
    suggestion_source: str = Field(default="manual", min_length=1, max_length=30)

    @model_validator(mode="after")
    def validate_reasons(self) -> "PriorityAssignmentInput":
        if self.rank in {PriorityRank.D, PriorityRank.E} and not (
            self.extra_slot_reason and self.extra_slot_reason.strip()
        ):
            raise ValueError("Ranks D and E require extra_slot_reason")
        if not self.competence_matches and not (
            self.cc_exception_reason and self.cc_exception_reason.strip()
        ):
            raise ValueError(
                "A Competence Category mismatch requires cc_exception_reason"
            )
        return self


class PriorityAssignmentRead(PrioritySchema):
    id: int
    plan_member_id: int
    demand_id: int
    job_id: int
    rank: PriorityRank
    channel: PriorityChannel
    verification_target: int
    recommendation_target: int
    competence_category_id: Optional[int]
    competence_matches: bool
    cc_exception_reason: Optional[str]
    extra_slot_reason: Optional[str]
    suggestion_source: str
    created_at: datetime
    updated_at: datetime


class PriorityPlanMemberInput(BaseModel):
    """Publish-time member shape.

    Draft endpoints may persist incomplete members one at a time, but the
    publish command must validate this complete shape.
    """

    user_id: int = Field(gt=0)
    status: PriorityMemberStatus = PriorityMemberStatus.active
    verification_capacity: int = Field(default=12, ge=0)
    capacity_reason: Optional[str] = Field(default=None, max_length=4000)
    paused_reason: Optional[str] = Field(default=None, max_length=4000)
    assignments: list[PriorityAssignmentInput] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_publish_member(self) -> "PriorityPlanMemberInput":
        if self.status == PriorityMemberStatus.paused:
            if not (self.paused_reason and self.paused_reason.strip()):
                raise ValueError("A paused member requires paused_reason")
            if self.assignments:
                raise ValueError("A paused member cannot have new assignments")
            return self

        assignment_count = len(self.assignments)
        if assignment_count > 5:
            raise ValueError("A member cannot have more than 5 assignments")

        actual_ranks = [assignment.rank for assignment in self.assignments]
        expected_ranks = list(PriorityRank)[:assignment_count]
        if sorted(actual_ranks, key=lambda rank: rank.value) != expected_ranks:
            raise ValueError("Assignment ranks must be unique and contiguous from A")

        job_ids = {assignment.job_id for assignment in self.assignments}
        if len(job_ids) != assignment_count:
            raise ValueError("A member cannot receive the same job more than once")

        return self


class PriorityPlanMemberRead(PrioritySchema):
    id: int
    plan_id: int
    user_id: int
    status: PriorityMemberStatus
    verification_capacity: int
    capacity_reason: Optional[str]
    paused_reason: Optional[str]
    assignments: list[PriorityAssignmentRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PriorityPlanCreate(BaseModel):
    notes: Optional[str] = Field(default=None, max_length=10000)
    previous_plan_id: Optional[int] = Field(default=None, gt=0)


class PriorityPlanDraftUpdate(BaseModel):
    expected_version: int = Field(gt=0)
    notes: Optional[str] = Field(default=None, max_length=10000)
    members: Optional[list[PriorityPlanMemberInput]] = None


class PriorityPlanPublishRequest(BaseModel):
    expected_version: int = Field(gt=0)
    members: list[PriorityPlanMemberInput] = Field(min_length=1)


class PriorityPlanRead(PrioritySchema):
    id: int
    version: int
    status: PriorityPlanStatus
    previous_plan_id: Optional[int]
    effective_from: Optional[datetime]
    review_due_at: Optional[datetime]
    published_at: Optional[datetime]
    superseded_at: Optional[datetime]
    created_by_user_id: Optional[int]
    published_by_user_id: Optional[int]
    notes: Optional[str]
    row_version: int
    members: list[PriorityPlanMemberRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class PriorityBlockerCreate(BaseModel):
    assignment_id: int = Field(gt=0)
    category: PriorityBlockerCategory
    description: str = Field(min_length=1, max_length=4000)
    evidence: Optional[dict[str, Any]] = None

    @field_validator("evidence")
    @classmethod
    def validate_evidence(
        cls,
        value: Optional[dict[str, Any]],
    ) -> Optional[dict[str, Any]]:
        return validate_blocker_evidence(value)


class PriorityBlockerDecision(BaseModel):
    expected_status: PriorityBlockerStatus = PriorityBlockerStatus.pending
    decision: PriorityBlockerStatus
    reason: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_decision(self) -> "PriorityBlockerDecision":
        if self.decision not in {
            PriorityBlockerStatus.accepted,
            PriorityBlockerStatus.rejected,
        }:
            raise ValueError("Blocker decision must be accepted or rejected")
        return self


class PriorityBlockerResolve(BaseModel):
    reason: Optional[str] = Field(default=None, max_length=4000)


class PriorityBlockerRead(PrioritySchema):
    id: int
    assignment_id: int
    reported_by_user_id: Optional[int]
    category: PriorityBlockerCategory
    description: str
    evidence: Optional[dict[str, Any]]
    status: PriorityBlockerStatus
    decided_by_user_id: Optional[int]
    decided_at: Optional[datetime]
    decision_reason: Optional[str]
    resolved_by_user_id: Optional[int]
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class PriorityExceptionCreate(BaseModel):
    user_id: int = Field(gt=0)
    job_id: int = Field(gt=0)
    origin_assignment_id: Optional[int] = Field(default=None, gt=0)
    reason: str = Field(min_length=1, max_length=4000)
    valid_from: datetime
    expires_at: datetime

    @model_validator(mode="after")
    def validate_window(self) -> "PriorityExceptionCreate":
        if self.expires_at <= self.valid_from:
            raise ValueError("expires_at must be later than valid_from")
        return self


class PriorityExceptionRead(PrioritySchema):
    id: int
    user_id: int
    job_id: int
    granted_by_user_id: Optional[int]
    origin_assignment_id: Optional[int]
    status: PriorityExceptionStatus
    reason: str
    valid_from: datetime
    expires_at: datetime
    consumed_at: Optional[datetime]
    consumed_candidate_id: Optional[int]
    consumed_process_id: Optional[int]
    created_at: datetime
    updated_at: datetime


class PriorityExceptionRevoke(BaseModel):
    reason: str = Field(min_length=1, max_length=4000)


class PriorityHandoffRequest(BaseModel):
    process_id: int = Field(gt=0)
    new_owner_user_id: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=4000)
    expected_process_version: int = Field(gt=0)


class PriorityUserModeUpdate(BaseModel):
    mode: PriorityMode
    reason: str = Field(min_length=1, max_length=4000)


class PriorityUserModeRead(PrioritySchema):
    user_id: int
    mode: PriorityMode
    set_by_user_id: Optional[int]
    reason: Optional[str]
    effective_at: datetime
    created_at: datetime
    updated_at: datetime


class PriorityAssignmentProgressRead(BaseModel):
    assignment: PriorityAssignmentRead
    verification_count: int = Field(ge=0)
    recommendation_count: int = Field(ge=0)
    target_reached: bool
    opening_allowed: bool
    blocking_reason: Optional[str] = None
    active_blockers: list[PriorityBlockerRead] = Field(default_factory=list)


class PriorityCarryOverRead(BaseModel):
    process_id: int
    candidate_id: int
    job_id: int
    owner_user_id: Optional[int]
    credit_user_id: Optional[int]
    current_semantic_state: Optional[str]
    origin_kind: Optional[PriorityOriginKind]
    urgent: bool = False
    opened_at: Optional[datetime]


class PriorityMyWorkRead(BaseModel):
    mode: PriorityMode
    plan: Optional[PriorityPlanRead]
    assignments: list[PriorityAssignmentProgressRead] = Field(default_factory=list)
    carry_over: list[PriorityCarryOverRead] = Field(default_factory=list)


class PriorityStateRead(PrioritySchema):
    id: int
    current_plan_id: Optional[int]
    row_version: int
    worker_heartbeat_at: Optional[datetime]
    last_reconciled_at: Optional[datetime]
    last_alert_sweep_at: Optional[datetime]
    last_error: Optional[str]
    metrics: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class PriorityAlertRead(PrioritySchema):
    id: int
    dedupe_key: str
    kind: str
    severity: PriorityAlertSeverity
    user_id: Optional[int]
    job_id: Optional[int]
    assignment_id: Optional[int]
    payload: dict[str, Any]
    occurrence_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    resolved_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


class PriorityAuditEventRead(PrioritySchema):
    id: int
    event_type: str
    actor_user_id: Optional[int]
    plan_id: Optional[int]
    subject_user_id: Optional[int]
    job_id: Optional[int]
    assignment_id: Optional[int]
    process_id: Optional[int]
    exception_id: Optional[int]
    payload: dict[str, Any]
    occurred_at: datetime
    correlation_id: Optional[str]


class PriorityReconciliationStatus(BaseModel):
    mode: PriorityMode
    current_plan_id: Optional[int]
    plan_overdue: bool
    users_without_coverage: int = Field(ge=0)
    unowned_carry_over: int = Field(ge=0)
    eligibility_coverage_percent: float = Field(ge=0, le=100)
    shadow_violation_count: int = Field(ge=0)
    worker_heartbeat_at: Optional[datetime]
    last_error: Optional[str]
