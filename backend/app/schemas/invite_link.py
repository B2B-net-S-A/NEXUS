"""Pydantic schemas for candidate invite links."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


InviteLinkStatus = Literal["active", "used", "revoked", "expired"]


class InviteLinkCreate(BaseModel):
    job_id: int = Field(..., description="Published job this link applies to.")
    label: Optional[str] = Field(
        default=None,
        max_length=120,
        description="Private recruiter note, e.g. 'LinkedIn post 04/26'.",
    )
    # 0339: brak/None = bez terminu — link żyje do zamknięcia rekrutacji.
    expires_in_days: Optional[Literal[7, 14, 30, 90]] = Field(
        default=None,
        description="Link validity window; null = valid until the job closes.",
    )


class InviteLinkJobBrief(BaseModel):
    id: int
    title: str


class InviteLinkCreatorBrief(BaseModel):
    id: int
    name: str


class InviteLinkResponse(BaseModel):
    token: str
    url: str
    public_url: str = ""
    kind: Literal["job", "recruiter"] = "job"
    slug: Optional[str] = None
    visit_count: int = 0
    job: InviteLinkJobBrief
    label: Optional[str] = None
    expires_at: Optional[datetime] = None
    revoked: bool = False
    use_count: int = 0
    last_used_at: Optional[datetime] = None
    created_at: datetime
    status: InviteLinkStatus
    origin_assignment_id: Optional[int] = None
    priority_compliant_at_create: Optional[bool] = None
    created_by_user: Optional[InviteLinkCreatorBrief] = None

    model_config = {"from_attributes": True}


# ── Strona kariery (0339) ─────────────────────────────────────────────────


class CareerLinkBrief(BaseModel):
    slug: str
    public_url: str
    created_at: datetime
    visit_count: int = 0


class CareerLinkStats(BaseModel):
    days: int = 30
    applications: int = 0
    new_candidates: int = 0


class CareerLinkJob(BaseModel):
    job_id: int
    title: str
    profile_status: Literal["none", "draft", "approved"]
    show_on_recruiter_page: bool
    has_link: bool


class CareerLinkResponse(BaseModel):
    link: Optional[CareerLinkBrief] = None
    stats: CareerLinkStats
    suggested_slug: str
    jobs: list[CareerLinkJob] = Field(default_factory=list)


class CareerLinkUpdate(BaseModel):
    slug: str = Field(..., min_length=1, max_length=64)


class SlugAvailability(BaseModel):
    available: bool
    reason: Optional[str] = None


class PublicSections(BaseModel):
    must: bool = True
    nice: bool = True
    params: bool = True
    process: bool = True


class PublicProfileFinding(BaseModel):
    code: Literal["client_name", "money", "contact", "person_name"]
    message: str
    excerpt: str


class PublicProfileUpdate(BaseModel):
    subtitle: Optional[str] = Field(default=None, max_length=300)
    about: Optional[str] = Field(default=None, max_length=4000)
    sections: Optional[PublicSections] = None
    show_on_recruiter_page: Optional[bool] = None


class PublicProfileVisibility(BaseModel):
    show_on_recruiter_page: bool


class PublicProfileResponse(BaseModel):
    job_id: int
    status: Literal["none", "draft", "approved"]
    subtitle: Optional[str] = None
    about: Optional[str] = None
    sections: PublicSections
    show_on_recruiter_page: bool = True
    approved_at: Optional[datetime] = None
    approved_by_name: Optional[str] = None
    findings: list[PublicProfileFinding] = Field(default_factory=list)
    preview: dict


class PublicProfileDraft(BaseModel):
    subtitle: str
    about: str
