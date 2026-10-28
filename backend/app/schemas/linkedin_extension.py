"""Schematy tras wtyczki LinkedIn (``/api/extension/*``). Kontrakt: ``extension/API.md``."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field

# Klucze ``client_off_limits.HOW_LABELS`` + ``skip`` („Nie, to my”).
OffLimitsHow = Literal[
    "linkedin_inbound",
    "job_ad",
    "phone_or_email",
    "sent_cv_before",
    "referral",
    "left_company",
    "skip",
]
ContactChannel = Literal["inmail", "invitation", "linkedin_message", "phone"]
MessageKind = Literal["inmail", "invitation", "linkedin_message"]


class ConnectRequest(BaseModel):
    extension_id: str = Field(min_length=1, max_length=64)
    extension_version: Optional[str] = Field(default=None, max_length=32)


class ExtensionUserBrief(BaseModel):
    id: int
    name: str
    initials: str


class UsageOut(BaseModel):
    reads_today: int
    reads_limit: int
    adds_today: int = 0


class ConnectResponse(BaseModel):
    key: str
    user: ExtensionUserBrief
    expires_at: datetime
    api_base: str
    frontend_url: str


class MeResponse(BaseModel):
    user: ExtensionUserBrief
    usage: UsageOut
    frontend_url: str


class ExperienceItem(BaseModel):
    title: Optional[str] = Field(default=None, max_length=300)
    company: Optional[str] = Field(default=None, max_length=300)
    start: Optional[str] = Field(default=None, max_length=20)
    end: Optional[str] = Field(default=None, max_length=20)
    current: bool = False


class ProfileRead(BaseModel):
    """Dane odczytane przez wtyczkę z otwartej strony LinkedIna."""

    page_kind: Literal["profile", "recruiter_profile", "search_result"] = "profile"
    page_url: Optional[str] = Field(default=None, max_length=1000)
    public_url: Optional[str] = Field(default=None, max_length=500)
    full_name: str = Field(min_length=1, max_length=200)
    headline: Optional[str] = Field(default=None, max_length=500)
    location: Optional[str] = Field(default=None, max_length=200)
    current_company: Optional[str] = Field(default=None, max_length=300)
    current_title: Optional[str] = Field(default=None, max_length=300)
    experience: list[ExperienceItem] = Field(default_factory=list, max_length=40)
    skills: list[str] = Field(default_factory=list, max_length=80)
    about: Optional[str] = Field(default=None, max_length=5000)


class CandidateBrief(BaseModel):
    id: int
    name: str
    headline: Optional[str] = None
    city: Optional[str] = None
    url: str
    in_nexus_since: Optional[date] = None


class AmbiguousItem(BaseModel):
    id: int
    name: str
    company: Optional[str] = None
    url: str


class OwnerOut(BaseModel):
    user_id: int
    name: str
    is_me: bool
    last_contact_at: Optional[datetime] = None


class ProcessOut(BaseModel):
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    stage_label: str
    recruiter_name: Optional[str] = None
    closed: bool = False
    close_label: Optional[str] = None
    updated_at: Optional[datetime] = None


class ContactOut(BaseModel):
    at: datetime
    user_name: Optional[str] = None
    channel_label: str
    note: Optional[str] = None


class RateOut(BaseModel):
    label: str
    as_of: Optional[date] = None


class RodoOut(BaseModel):
    status: Literal["valid", "expired", "none"]
    label: str


class OffLimitsOut(BaseModel):
    client_name: str
    company: str


class ContractorOut(BaseModel):
    client_name: Optional[str] = None
    end_date: Optional[date] = None
    delivery_lead_name: Optional[str] = None


class JobChangeOut(BaseModel):
    page_company: str
    nexus_company: Optional[str] = None


class JobMatchOut(BaseModel):
    job_id: int
    title: str
    client_name: Optional[str] = None
    recruiter_name: Optional[str] = None
    score: int


class LookupResponse(BaseModel):
    status: Literal["found", "not_found", "ambiguous"]
    matched_by: Optional[Literal["linkedin", "name_company"]] = None
    candidate: Optional[CandidateBrief] = None
    ambiguous: list[AmbiguousItem] = Field(default_factory=list)
    owner: Optional[OwnerOut] = None
    processes: list[ProcessOut] = Field(default_factory=list)
    contacts: list[ContactOut] = Field(default_factory=list)
    rate: Optional[RateOut] = None
    rodo: Optional[RodoOut] = None
    off_limits: Optional[OffLimitsOut] = None
    contractor: Optional[ContractorOut] = None
    job_change: Optional[JobChangeOut] = None
    matches: list[JobMatchOut] = Field(default_factory=list)
    usage: UsageOut


class BatchPerson(BaseModel):
    full_name: str = Field(min_length=1, max_length=200)
    public_url: Optional[str] = Field(default=None, max_length=500)
    headline: Optional[str] = Field(default=None, max_length=500)
    current_company: Optional[str] = Field(default=None, max_length=300)


class BatchRequest(BaseModel):
    people: list[BatchPerson] = Field(min_length=1, max_length=50)


class BatchItem(BaseModel):
    index: int
    status: Literal["new", "in_process", "in_base", "off_limits", "contractor"]
    candidate_id: Optional[int] = None
    label: Optional[str] = None
    score: Optional[int] = None


class BatchResponse(BaseModel):
    items: list[BatchItem]
    usage: UsageOut


class JobOption(BaseModel):
    id: int
    title: str
    client_name: Optional[str] = None
    recruiter_name: Optional[str] = None


class JobOptionsResponse(BaseModel):
    items: list[JobOption]


class AddCandidateRequest(BaseModel):
    profile: ProfileRead
    job_ids: list[int] = Field(default_factory=list, max_length=10)
    off_limits_how: Optional[OffLimitsHow] = None


class SkippedJob(BaseModel):
    job_id: int
    reason: str


class AddCandidateResponse(BaseModel):
    candidate_id: int
    url: str
    created: bool
    assigned_job_ids: list[int] = Field(default_factory=list)
    skipped: list[SkippedJob] = Field(default_factory=list)


class AssignJobsRequest(BaseModel):
    job_ids: list[int] = Field(min_length=1, max_length=10)
    off_limits_how: Optional[OffLimitsHow] = None


class AssignJobsResponse(BaseModel):
    assigned_job_ids: list[int] = Field(default_factory=list)
    skipped: list[SkippedJob] = Field(default_factory=list)


class RefreshRequest(BaseModel):
    profile: ProfileRead


class RefreshResponse(BaseModel):
    updated: list[str]


class ContactRequest(BaseModel):
    channel: ContactChannel
    job_id: Optional[int] = None
    note: Optional[str] = Field(default=None, max_length=2000)
    remind_in_days: Optional[int] = Field(default=None, ge=1, le=30)


class ContactResponse(BaseModel):
    id: int
    reminder_id: Optional[int] = None


class NoteRequest(BaseModel):
    text: str = Field(min_length=1, max_length=5000)


class IdResponse(BaseModel):
    id: int


class ProfilePdfResponse(BaseModel):
    document_id: int


class DraftRequest(BaseModel):
    job_id: int
    kind: MessageKind
    profile: ProfileRead


class DraftResponse(BaseModel):
    text: str
    ai: bool


class ConnectionAdminOut(BaseModel):
    key_id: str
    user_id: int
    user_name: str
    extension_version: Optional[str] = None
    created_at: datetime
    expires_at: datetime
    last_used_at: Optional[datetime] = None
    reads_today: int
    adds_today: int


class ConnectionsAdminResponse(BaseModel):
    items: list[ConnectionAdminOut]
    reads_limit: int
