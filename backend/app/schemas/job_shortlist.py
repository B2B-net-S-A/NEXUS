"""Pydantic schemas for the job shortlist (SEARCH-P1-05)."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

EvaluationStatus = Literal["do_oceny", "potencjalny", "zatwierdzony", "odrzucony"]
OutreachStatus = Literal[
    "nie_kontaktowano",
    "do_kontaktu",
    "kontakt_w_toku",
    "zainteresowany",
    "brak_zainteresowania",
]


class ShortlistAddRequest(BaseModel):
    candidate_ids: list[int] = Field(..., min_length=1, max_length=100)
    note: Optional[str] = Field(default=None, max_length=2000)


class ShortlistUpdateRequest(BaseModel):
    """Partial update. ``version`` is the optimistic-lock guard — it must match
    the row's current version or the PATCH 409s."""

    version: int = Field(..., ge=1)
    evaluation_status: Optional[EvaluationStatus] = None
    outreach_status: Optional[OutreachStatus] = None
    owner_id: Optional[int] = None
    decision_reason_code: Optional[str] = Field(default=None, max_length=64)
    note: Optional[str] = Field(default=None, max_length=2000)
    next_action_at: Optional[datetime] = None


class ShortlistEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    candidate_id: int
    candidate_name: Optional[str] = None
    candidate_lastname: Optional[str] = None
    evaluation_status: str
    outreach_status: str
    owner_id: Optional[int] = None
    decision_reason_code: Optional[str] = None
    note: Optional[str] = None
    next_action_at: Optional[datetime] = None
    score_snapshot: Optional[int] = None
    version: int
    promoted_to_pipeline_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ShortlistAddResponse(BaseModel):
    added: list[int]
    skipped: list[int]
    total_added: int
    total_skipped: int


class ShortlistPromoteResponse(BaseModel):
    entry_id: int
    candidate_id: int
    job_id: int
    stage_id: int
    already_promoted: bool = False
    already_in_pipeline: bool = False
