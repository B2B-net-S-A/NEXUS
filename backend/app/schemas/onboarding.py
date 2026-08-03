"""Pydantic payloads for the first-login onboarding flow.

The endpoint is role-dispatched at runtime (see backend/app/api/onboarding.py):
Delivery Leads send `OnboardingPayloadDL`, recruiters send
`OnboardingPayloadRecruiter`. Both roles may submit empty lists — the flag
still flips to true so the rollout does not trap users with no data yet.
"""

from typing import List

from pydantic import BaseModel, Field

from app.models.job import JobStatus, Seniority
from app.schemas.user import UserResponse


class OnboardingJobOption(BaseModel):
    """Minimal, non-financial job projection shown before onboarding."""

    id: int
    title: str
    client_name: str | None = None
    location: str | None = None
    status: JobStatus
    seniority: Seniority | None = None


class OnboardingJobsResponse(BaseModel):
    items: list[OnboardingJobOption]
    total: int


class OnboardingPayloadDL(BaseModel):
    """Body expected from a Delivery Lead.

    - `priority_job_ids`: jobs to mark as `priority='high'` (Lista priorytetów).
    - `needs_sourcing_job_ids`: jobs to mark as `needs_sourcing=true`
      (Potrzebny search).
    """

    priority_job_ids: List[int] = Field(default_factory=list)
    needs_sourcing_job_ids: List[int] = Field(default_factory=list)


class OnboardingPayloadRecruiter(BaseModel):
    """Body expected from a recruiter.

    `active_job_ids` = jobs the recruiter is actively working on
    ("Aktywni w searchu"). Inserted into `job_collaborators`; the primary
    `jobs.recruiter_id` owner is not touched.
    """

    active_job_ids: List[int] = Field(default_factory=list)


class OnboardingResponse(BaseModel):
    """Updated user returned so the frontend can refresh its auth store."""

    user: UserResponse
