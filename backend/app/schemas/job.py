from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.job import JobPriority, JobStatus, RemotePolicy, RecruitmentType


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
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int
