"""Pydantic schemas for the 'Historia requestu' tab + new-role wizard banner."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field

from app.schemas.money import WholePLN


class RequestHistoryEntry(BaseModel):
    """Mirror of services.request_history.RequestHistoryEntry for the API layer."""

    job_id: int
    title: str
    train_name: Optional[str] = None
    same_train: bool = False
    seniority: Optional[str] = None
    status: str
    is_in_progress: bool
    outcome: Optional[Literal["filled", "cancelled"]] = None
    close_reason: Optional[str] = None
    similarity: float
    similarity_source: Literal["sql_same_client", "voyage"]
    closed_at: Optional[datetime] = None
    created_at: datetime
    tth_days: Optional[int] = None
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    champion_name: Optional[str] = None
    champion_candidate_id: Optional[int] = None
    champions_count: int = 0
    candidates_count: int = 0
    fee_rate: Optional[WholePLN] = None
    fee_currency: Optional[str] = None
    rate_unit: Optional[str] = None
    tac_name: Optional[str] = None
    delivery_lead_name: Optional[str] = None


class RequestHistoryMeta(BaseModel):
    """Counters + aux info for the API response."""

    sql_count: int = 0
    voyage_count: int = 0
    total: int = 0
    skill_freq_sample: int = 0  # how many closed jobs fed into skill_frequency


class RequestHistoryResponse(BaseModel):
    """Response for both GET /jobs/{id}/request-history and POST .../preview."""

    closed: List[RequestHistoryEntry] = Field(default_factory=list)
    in_progress: List[RequestHistoryEntry] = Field(default_factory=list)
    skill_frequency: dict[str, Any] = Field(default_factory=dict)
    meta: RequestHistoryMeta = Field(default_factory=RequestHistoryMeta)


class RequestHistoryPreviewRequest(BaseModel):
    """Wizard banner — preview matches BEFORE the job row is saved."""

    title: str = Field(min_length=1, max_length=500)
    client_id: Optional[int] = Field(default=None, gt=0)
    raw_description: Optional[str] = Field(default=None, max_length=50_000)
    train_name: Optional[str] = Field(default=None, max_length=128)
    top_k: int = Field(default=5, ge=1, le=30)
    cross_client: bool = False
    include_open: bool = True


class AddCandidateFromHistoryPayload(BaseModel):
    """Body for POST /jobs/{job_id}/candidates — adds candidate as new pipeline entry.

    `source_job_id` is metadata-only and lands in the activity log so we can
    surface 'imported from job N' in the UI without inventing a new column.
    """

    candidate_id: int = Field(gt=0)
    source_job_id: Optional[int] = Field(default=None, gt=0)


class AddCandidateFromHistoryResponse(BaseModel):
    candidate_stage_id: int
    job_id: int
    candidate_id: int
    stage: str
    source_job_id: Optional[int] = None
