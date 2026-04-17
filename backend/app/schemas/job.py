from datetime import date, datetime
from typing import Any, List, Optional

from pydantic import BaseModel, field_validator

from app.models.job import (
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

    @field_validator("must_skills", "nice_skills", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
