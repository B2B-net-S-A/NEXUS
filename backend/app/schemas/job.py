from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, field_validator

from app.models.job import (
    JobCloseReason,
    JobPriority,
    JobStatus,
    RecruitmentType,
    RemotePolicy,
    Seniority,
    WorkMode,
)
from app.schemas.candidate import _normalize_skill_list


class JobCreate(BaseModel):
    title: str
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote_policy: RemotePolicy = RemotePolicy.hybrid
    status: JobStatus = JobStatus.draft
    priority: JobPriority = JobPriority.medium
    needs_sourcing: bool = False
    recruitment_type: RecruitmentType = RecruitmentType.body_leasing
    deadline: Optional[date] = None
    client_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    portals: Optional[Any] = None

    # Phase 1 structured fields
    must_skills: Optional[List[Any]] = None
    nice_skills: Optional[List[Any]] = None
    seniority: Optional[Seniority] = None
    work_mode: WorkMode = WorkMode.fulltime
    headcount: int = 1
    reference_number: Optional[str] = None
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    custom_fields: Optional[dict] = None
    pipeline_template_id: Optional[int] = None

    # AI CC matching (migracja 0041). Jeśli `competence_category_id` podane —
    # używamy jawnie; jeśli None + `auto_suggest_cc=true` — classifier wybiera
    # top-1 (albo zostawia None gdy remis <0.10). `secondary_cc_ids` do wider
    # matchingu (max 2, validated w endpointzie).
    competence_category_id: Optional[int] = None
    secondary_cc_ids: Optional[List[int]] = None
    auto_suggest_cc: bool = True

    @field_validator("must_skills", "nice_skills", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


class JobUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    requirements: Optional[str] = None
    location: Optional[str] = None
    salary_min: Optional[int] = None
    salary_max: Optional[int] = None
    remote_policy: Optional[RemotePolicy] = None
    status: Optional[JobStatus] = None
    priority: Optional[JobPriority] = None
    needs_sourcing: Optional[bool] = None
    recruitment_type: Optional[RecruitmentType] = None
    deadline: Optional[date] = None
    client_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    portals: Optional[Any] = None

    # Phase 1 structured fields
    must_skills: Optional[List[Any]] = None
    nice_skills: Optional[List[Any]] = None
    seniority: Optional[Seniority] = None
    work_mode: Optional[WorkMode] = None
    headcount: Optional[int] = None
    reference_number: Optional[str] = None
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    custom_fields: Optional[dict] = None
    pipeline_template_id: Optional[int] = None
    competence_category_id: Optional[int] = None
    secondary_cc_ids: Optional[List[int]] = None

    @field_validator("must_skills", "nice_skills", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


class CcSuggestion(BaseModel):
    """Pojedyncza sugestia CC z wyjaśnieniem decyzji."""

    competence_category_id: int
    slug: str
    name_pl: str
    score: float  # 0..1
    confidence_band: str  # "high" | "medium" | "low"
    keywords_matched: List[str] = []


class CcSuggestionsResponse(BaseModel):
    """Zwracana z POST /jobs (response) i POST /jobs/{id}/classify-cc."""

    top: Optional[CcSuggestion] = None
    alternatives: List[CcSuggestion] = []
    tie: bool = False  # True gdy |top-1 − top-2| < 0.10


class CcOverrideRequest(BaseModel):
    """Log override gdy DL zmienia sugerowaną CC."""

    suggested_cc_id: Optional[int] = None
    final_cc_id: Optional[int] = None
    suggested_score: Optional[float] = None


class JobResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    requirements: Optional[str]
    location: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    remote_policy: RemotePolicy
    status: JobStatus
    priority: JobPriority
    needs_sourcing: bool = False
    recruitment_type: RecruitmentType
    deadline: Optional[date]
    client_id: Optional[int]
    recruiter_id: Optional[int]
    created_by: Optional[int]
    portals: Optional[Any]
    must_skills: Optional[Any] = None
    nice_skills: Optional[Any] = None
    seniority: Optional[Seniority] = None
    work_mode: WorkMode = WorkMode.fulltime
    headcount: int = 1
    reference_number: Optional[str] = None
    industry: Optional[str] = None
    subcategory: Optional[str] = None
    custom_fields: Optional[Any] = None
    champion_profile: Optional[Any] = None
    embedding_id: Optional[str] = None
    criteria_generated_at: Optional[datetime] = None
    pipeline_template_id: Optional[int] = None
    competence_category_id: Optional[int] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[JobCloseReason] = None
    close_notes: Optional[str] = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int


class UserBrief(BaseModel):
    """Minimal user projection embedded in job owner/collaborator responses."""

    id: int
    email: str
    name: str
    role: Optional[str] = None

    model_config = {"from_attributes": True}

    @field_validator("role", mode="before")
    @classmethod
    def _role_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return getattr(v, "value", str(v))


class JobOwnerAssignment(BaseModel):
    """Set, change, or clear the primary owner (recruiter_id).

    Admin + Delivery Lead only. `recruiter_id = None` clears the assignment.
    """

    recruiter_id: Optional[int] = None


class JobCollaboratorAdd(BaseModel):
    """Add a collaborator (read-only participant) to a job."""

    user_id: int


class JobCloseRequest(BaseModel):
    """Payload for POST /jobs/{id}/close — records why the job was closed."""

    reason: JobCloseReason
    notes: Optional[str] = None
