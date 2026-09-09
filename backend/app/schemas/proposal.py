"""Pydantic schemas for AI proposal snapshots."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel


class ProposalCandidate(BaseModel):
    """Hydrated candidate row attached to a proposal (for UI rendering).

    Mirrors the fields used by `SuggestedCandidatesWidget` on the frontend so the
    component can render a row without re-fetching the candidate separately.
    """

    id: int
    name: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    status: Optional[str] = None
    champion: Optional[bool] = None

    model_config = {"from_attributes": True}


class ProposalCandidateItem(BaseModel):
    """One ranked candidate inside a snapshot."""

    candidate: ProposalCandidate
    total_score: float | None
    breakdown: dict[str, Any]


class ProposalSnapshotResponse(BaseModel):
    id: int
    job_id: int
    status: str  # "pending" | "ready" | "failed"
    source: str  # "create" | "manual_regenerate" | "job_updated"
    top_k: int
    profile_id: int
    created_at: datetime
    error_message: Optional[str] = None
    degraded: bool = False
    stale: bool = False
    # Liczniki dealbreakerów z generacji ({"over_budget": N, "remote_only": M});
    # None = snapshot sprzed 0237. UI renderuje z tego chip „ukryto N" —
    # ukrywanie nigdy nie jest ciche.
    hidden: Optional[dict[str, int]] = None
    run_id: Optional[str] = None
    candidates: List[ProposalCandidateItem] = []

    model_config = {"from_attributes": True}


class ProposalSnapshotSummary(BaseModel):
    """Trimmed version for the list endpoint (no breakdowns, no hydrated candidates)."""

    id: int
    job_id: int
    status: str
    source: str
    top_k: int
    created_at: datetime
    candidate_count: int
    error_message: Optional[str] = None
    degraded: bool = False
    stale: bool = False

    model_config = {"from_attributes": True}


class ProposalListResponse(BaseModel):
    items: List[ProposalSnapshotSummary]
    total: int
    page: int
    page_size: int
