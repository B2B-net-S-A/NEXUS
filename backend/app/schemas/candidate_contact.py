"""API contracts for global candidate contact coordination."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

ContactCaseState = Literal[
    "unassigned",
    "awaiting_capacity",
    "queued",
    "callback_due",
    "cooldown",
    "handoff_pending",
    "blocked_no_phone",
    "suppressed",
    "completed",
    "cancelled",
]
ContactOutcome = Literal[
    "connected",
    "no_answer",
    "callback_requested",
    "wrong_number",
    "do_not_contact",
]
OpportunityOutcome = Literal["interested", "maybe", "not_interested", "not_presented"]


class ContactOpportunityOutcomeInput(BaseModel):
    job_id: int = Field(..., ge=1)
    outcome: OpportunityOutcome


class ContactAttemptCreate(BaseModel):
    expected_version: int = Field(..., ge=1)
    outcome: ContactOutcome
    opportunity_outcomes: list[ContactOpportunityOutcomeInput] = Field(
        default_factory=list
    )
    callback_at: Optional[datetime] = None
    notes: Optional[str] = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def validate_callback(self) -> "ContactAttemptCreate":
        needs_callback = self.outcome == "callback_requested" or any(
            item.outcome in {"maybe", "not_presented"}
            for item in self.opportunity_outcomes
        )
        if needs_callback and self.callback_at is None:
            raise ValueError(
                "callback_at is required for callback_requested, maybe or not_presented"
            )
        return self


class ContactReassignRequest(BaseModel):
    expected_version: Optional[int] = Field(default=None, ge=1)
    target_user_id: Optional[int] = Field(default=None, ge=1)
    reason: str = Field(..., min_length=1, max_length=500)


class ContactOpportunityResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    case_id: int
    candidate_id: int
    job_id: int
    source: str
    source_external_ref: Optional[str] = None
    linked_at: datetime
    outcome: Optional[str] = None
    presented_at: Optional[datetime] = None
    meeting_event_id: Optional[int] = None
    meeting_scheduled_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    closed_reason: Optional[str] = None


class ContactCaseResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    candidate_id: int
    owner_user_id: Optional[int] = None
    previous_owner_user_id: Optional[int] = None
    primary_job_id: Optional[int] = None
    state: str
    due_at: Optional[datetime] = None
    cooldown_until: Optional[datetime] = None
    attempt_count: int
    cycle: int
    queue_slot: Optional[int] = None
    version: int
    assigned_at: Optional[datetime] = None
    last_attempt_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    opportunities: list[ContactOpportunityResponse] = Field(default_factory=list)


class ContactOwnerSummary(BaseModel):
    id: int
    name: str


class ContactCaseSummaryResponse(BaseModel):
    """Bounded badge projection embedded in candidate/pipeline payloads."""

    id: int
    status: ContactCaseState
    owner: Optional[ContactOwnerSummary] = None
    due_at: Optional[datetime] = None
    callback_at: Optional[datetime] = None
    attempts_in_cycle: int = 0
    version: int


class ContactAttemptResponse(BaseModel):
    case: ContactCaseResponse
    call_id: int
    replayed: bool = False


class ContactQueueCapacity(BaseModel):
    used: int = Field(..., ge=0, le=20)
    limit: int = Field(default=20, ge=20, le=20)


class ContactProcessingStats(BaseModel):
    scanned: int = 0
    reassigned: int = 0
    cooldown_released: int = 0
    phone_restored: int = 0
    assigned_from_waiting: int = 0
    completed: int = 0
