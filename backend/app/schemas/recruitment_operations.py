"""Narrow API contracts for the recruitment operations dashboard."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


RecruitmentOperationsPreset = Literal[
    "admin-ops",
    "delivery-lead",
    "finance",
    "head-of-recruitment",
    "my-work",
]


class RecruitmentOperationsModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RecruitmentOperationsPerson(RecruitmentOperationsModel):
    id: int
    name: str


class RecruitmentOperationsLookup(RecruitmentOperationsModel):
    id: int | None
    name: str


class RecruitmentOperationsStageCounts(RecruitmentOperationsModel):
    new: int = 0
    screening: int = 0
    cv_sent: int = 0
    client_interview: int = 0
    acceptance: int = 0


class RecruitmentOperationsFavorite(RecruitmentOperationsModel):
    id: int
    name: str
    stage: str


class RecruitmentOperationsOwners(RecruitmentOperationsModel):
    recruiter: RecruitmentOperationsPerson | None = None
    tac: RecruitmentOperationsPerson | None = None
    delivery_lead: RecruitmentOperationsPerson | None = None
    collaborators: list[RecruitmentOperationsPerson] = Field(default_factory=list)


class RecruitmentOperationsProcess(RecruitmentOperationsModel):
    job_id: int
    title: str
    client: RecruitmentOperationsLookup
    competence_category: RecruitmentOperationsLookup | None = None
    candidate_count: int
    shared_candidate_count: int = 0
    stage_counts: RecruitmentOperationsStageCounts
    favorite_candidate: RecruitmentOperationsFavorite | None = None
    owners: RecruitmentOperationsOwners
    href: str


class RecruitmentOperationsSummary(RecruitmentOperationsModel):
    open_processes: int
    competence_categories: int
    active_candidates: int
    processes_without_favorite: int
    shared_candidates: int = 0
    processes_with_shared_candidates: int = 0


class RecruitmentOperationsCategory(RecruitmentOperationsModel):
    id: int | None
    name: str
    total: int
    shared_candidates: int = 0
    processes_with_shared_candidates: int = 0


class RecruitmentOperationsListResponse(RecruitmentOperationsModel):
    generated_at: datetime
    page: int
    page_size: int
    total: int
    summary: RecruitmentOperationsSummary
    categories: list[RecruitmentOperationsCategory] = Field(default_factory=list)
    items: list[RecruitmentOperationsProcess] = Field(default_factory=list)


class RecruitmentOperationsFavoriteOption(RecruitmentOperationsModel):
    id: int
    name: str
    stage: str


class RecruitmentOperationsSimilarProcess(RecruitmentOperationsModel):
    job_id: int
    title: str
    client: RecruitmentOperationsLookup
    competence_category: RecruitmentOperationsLookup | None = None
    similarity: float
    candidate_overlap: int
    href: str


SimilarityStatus = Literal["primary", "extended", "empty", "degraded"]


class RecruitmentOperationsDetailResponse(RecruitmentOperationsModel):
    generated_at: datetime
    process: RecruitmentOperationsProcess
    can_edit_favorite: bool
    favorite_options: list[RecruitmentOperationsFavoriteOption] = Field(
        default_factory=list
    )
    similarity_status: SimilarityStatus
    similar_processes: list[RecruitmentOperationsSimilarProcess] = Field(
        default_factory=list
    )


class RecruitmentOperationsFavoriteUpdate(RecruitmentOperationsModel):
    candidate_id: int | None
