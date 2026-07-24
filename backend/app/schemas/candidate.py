from datetime import date, datetime
from enum import Enum
from typing import Any, List, Literal, Optional

from pydantic import BaseModel, EmailStr, Field, field_validator

from app.models.candidate import AvailabilityStatus, CandidateStatus
from app.models.linkedin_snapshot import LinkedinChangeKind, LinkedinSyncStatus
from app.models.recruitment_pipeline import PipelineStage


class EmploymentState(str, Enum):
    """
    Derived fact about current engagement — computed from active contracts
    and `current_employment` conflicts. Not persisted on `candidates`.
    """

    employed_at_client = "employed_at_client"
    on_bench = "on_bench"
    external = "external"
    unknown = "unknown"


class EmploymentInfo(BaseModel):
    """
    Employment snapshot rendered next to every candidate in the list/profile.
    `source` exposes whether the fact came from a live Contract, a manual
    CandidateConflict, or the recruitment pipeline (a `hired` stage) so the UI
    can show a different tooltip.
    """

    state: EmploymentState
    client_id: Optional[int] = None
    client_name: Optional[str] = None
    contract_id: Optional[int] = None
    job_id: Optional[int] = None
    contract_end_date: Optional[date] = None
    source: Literal["contract", "conflict", "pipeline", "none"] = "none"


_VALID_SKILL_LEVELS = {"expert", "senior", "mid", "junior", None}


def _normalize_skill_list(value: Any) -> Optional[List[dict]]:
    """
    Normalize a skills list into structured form:
      [{"name": str, "level": str|None, "years": int|None, "category": str|None}, ...]

    Accepts:
      - None → None
      - list of strings → wrapped as {name:str, level:None}
      - list of dicts → validated/passed through
    """
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError("skills must be a list")

    normalized: List[dict] = []
    for item in value:
        if isinstance(item, str):
            normalized.append({"name": item.strip(), "level": None})
        elif isinstance(item, dict):
            name = item.get("name")
            if not isinstance(name, str) or not name.strip():
                raise ValueError(
                    f"skill item requires non-empty 'name' string, got {item!r}"
                )
            level = item.get("level")
            if level is not None and level not in _VALID_SKILL_LEVELS:
                raise ValueError(
                    f"skill level must be one of {sorted(v for v in _VALID_SKILL_LEVELS if v)}, got {level!r}"
                )
            entry = {"name": name.strip(), "level": level}
            if "years" in item and item["years"] is not None:
                entry["years"] = int(item["years"])
            if "category" in item and item["category"] is not None:
                entry["category"] = str(item["category"]).strip()
            normalized.append(entry)
        else:
            raise ValueError(
                f"skill item must be str or dict, got {type(item).__name__}"
            )
    return normalized


class CandidateCreate(BaseModel):
    name: str
    lastname: str
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    salary_expectation: Optional[int] = None
    salary_currency: Optional[str] = "PLN"
    expected_rate_hourly: Optional[int] = None
    expected_rate_currency: Optional[str] = "PLN"
    availability_date: Optional[date] = None
    notice_period: Optional[int] = None
    notice_period_unit: Optional[Literal["days", "weeks", "months"]] = None
    source: Optional[str] = None
    status: CandidateStatus = CandidateStatus.active
    availability_status: AvailabilityStatus = AvailabilityStatus.unknown
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None
    preferences: Optional[dict] = None
    champion: bool = False
    verifier_id: Optional[int] = None
    verified_tech: Optional[List[Any]] = None

    @field_validator("skills", "verified_tech", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)


class CandidateUpdate(BaseModel):
    name: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[EmailStr] = None
    phone: Optional[str] = None
    location: Optional[str] = None
    linkedin: Optional[str] = None
    salary_expectation: Optional[int] = None
    salary_currency: Optional[str] = None
    expected_rate_hourly: Optional[int] = None
    expected_rate_currency: Optional[str] = None
    availability_date: Optional[date] = None
    notice_period: Optional[int] = None
    notice_period_unit: Optional[Literal["days", "weeks", "months"]] = None
    source: Optional[str] = None
    status: Optional[CandidateStatus] = None
    availability_status: Optional[AvailabilityStatus] = None
    avatar_url: Optional[str] = None
    competence_category: Optional[str] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    tags: Optional[List[Any]] = None
    skills: Optional[List[Any]] = None
    experience: Optional[List[Any]] = None
    education: Optional[List[Any]] = None
    languages: Optional[List[Any]] = None
    preferences: Optional[dict] = None
    champion: Optional[bool] = None
    verifier_id: Optional[int] = None
    verified_tech: Optional[List[Any]] = None
    # Engagement flags — consultant-level cues for extra value.
    is_ambassador: Optional[bool] = None
    wants_to_verify_candidates: Optional[bool] = None
    open_to_side_projects: Optional[bool] = None
    open_to_sales_support: Optional[bool] = None
    open_to_expert_consult: Optional[bool] = None
    engagement_notes: Optional[str] = None
    # Structured location.
    city: Optional[str] = None
    country: Optional[str] = Field(default=None, max_length=2)
    region: Optional[str] = None
    hub_city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Business entity / JDG (migracja 0058) — używane przy generowaniu umów.
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    business_address: Optional[str] = None
    business_form: Optional[str] = None

    @field_validator("skills", "verified_tech", mode="before")
    @classmethod
    def _normalize_skills(cls, v: Any) -> Any:
        return _normalize_skill_list(v)

    @field_validator("country", mode="before")
    @classmethod
    def _uppercase_country(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().upper() or None
        return v


class CandidateEngagementUpdate(BaseModel):
    """Convenience schema for PATCH /{id}/engagement."""

    is_ambassador: Optional[bool] = None
    wants_to_verify_candidates: Optional[bool] = None
    open_to_side_projects: Optional[bool] = None
    open_to_sales_support: Optional[bool] = None
    open_to_expert_consult: Optional[bool] = None
    engagement_notes: Optional[str] = None


class CandidateLocationUpdate(BaseModel):
    """Convenience schema for PATCH /{id}/location."""

    city: Optional[str] = None
    country: Optional[str] = Field(default=None, max_length=2)
    region: Optional[str] = None
    hub_city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None

    @field_validator("country", mode="before")
    @classmethod
    def _uppercase_country(cls, v: Any) -> Any:
        if isinstance(v, str):
            return v.strip().upper() or None
        return v


class MatchStats(BaseModel):
    """Lightweight summary used by the candidates list badge (Phase A1)."""

    open_count: int
    total_open: int
    top_score: float


class CandidateCreatorBrief(BaseModel):
    """Minimal creator info for the "Dodał" column in the candidates list."""

    id: int
    name: str

    model_config = {"from_attributes": True}


class TalentPoolBrief(BaseModel):
    """Minimal pool info for the candidate tile/list chips."""

    id: int
    name: str

    model_config = {"from_attributes": True}


class ActiveRecruitmentBrief(BaseModel):
    """Rekrutacja kandydata — używana w liście kandydatów do pokazania w jakich
    pipeline'ach kandydat się znajduje. Obejmuje WSZYSTKIE etapy, też terminalne
    (rejected/withdrawn/hired) — front różnicuje status badge'em, więc odrzucony
    czy zatrudniony kandydat nadal jest widoczny. Wyłącznie najnowszy ruch per
    (candidate_id, job_id).

    `moved_at` / `moved_by_name` opisują KTO i KIEDY przeniósł kandydata na
    jego BIEŻĄCY etap w tej rekrutacji (= ten sam najnowszy ruch). Pozwala
    rekruterowi sprawdzić atrybucję wprost z listy (popover „Rekrutacje").
    """

    job_id: int
    job_title: str
    client_name: Optional[str] = None
    stage: PipelineStage
    moved_at: Optional[datetime] = None
    moved_by_name: Optional[str] = None


class LinkedinSnapshotSummary(BaseModel):
    """One LinkedIn profile snapshot surfaced in the candidate detail view.

    Full `profile_json` stays on the server — the UI only needs the derived
    fields (company/title/started_at) + the change_kind label.
    """

    id: int
    fetched_at: datetime
    current_company: Optional[str] = None
    current_title: Optional[str] = None
    current_started_at: Optional[date] = None
    change_kind: LinkedinChangeKind
    changed_from_previous: bool = False

    model_config = {"from_attributes": True}


class CandidateLinkedinSyncResponse(BaseModel):
    """Response of POST /candidates/{id}/sync-linkedin."""

    status: Literal["queued", "ok", "not_found", "error", "disabled"]
    candidate_id: int
    message: Optional[str] = None


class InviteSourceBrief(BaseModel):
    """Surfaces that a candidate entered through an invite link — so the
    profile view can show a badge and Timeline can render an ownership
    transfer event. Populated via a server-side join (latest
    `applied_via_invite` Activity + matching CandidateInviteLink).
    """

    label: Optional[str] = None
    created_by_name: str
    applied_at: datetime
    previous_created_by_name: Optional[str] = None


class CandidateResponse(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str]
    phone: Optional[str]
    location: Optional[str]
    linkedin: Optional[str]
    avatar_url: Optional[str] = None
    salary_expectation: Optional[int]
    salary_currency: Optional[str] = "PLN"
    expected_rate_hourly: Optional[int] = None
    expected_rate_currency: Optional[str] = "PLN"
    availability_date: Optional[date]
    notice_period: Optional[int] = None
    notice_period_unit: Optional[Literal["days", "weeks", "months"]] = None
    source: Optional[str]
    competence_category: Optional[str] = None
    # Primary competence-category FK (kept in sync with the M2M primary). The
    # frontend maps this id → display name via GET /api/competence-categories.
    competence_category_id: Optional[int] = None
    years_it_experience: Optional[int] = None
    ai_summary: Optional[str] = None
    status: CandidateStatus
    availability_status: AvailabilityStatus = AvailabilityStatus.unknown
    employment: EmploymentInfo = EmploymentInfo(state=EmploymentState.unknown)
    tags: Optional[Any]
    skills: Optional[Any]
    experience: Optional[Any]
    education: Optional[Any]
    languages: Optional[Any]
    preferences: Optional[Any] = None
    champion: bool = False
    verifier_id: Optional[int] = None
    verified_tech: Optional[Any] = None
    # Engagement flags (Kontrakty expansion)
    is_ambassador: bool = False
    wants_to_verify_candidates: bool = False
    open_to_side_projects: bool = False
    open_to_sales_support: bool = False
    open_to_expert_consult: bool = False
    # TTL/freshness timestamps (Phase „Otwartość" Faza 2).
    open_to_side_projects_updated_at: Optional[datetime] = None
    open_to_sales_support_updated_at: Optional[datetime] = None
    open_to_expert_consult_updated_at: Optional[datetime] = None
    engagement_notes: Optional[str] = None
    # Structured location (Kontrakty expansion)
    city: Optional[str] = None
    country: Optional[str] = None
    region: Optional[str] = None
    hub_city: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    # Business entity / JDG (migracja 0058)
    legal_name: Optional[str] = None
    nip: Optional[str] = None
    regon: Optional[str] = None
    business_address: Optional[str] = None
    business_form: Optional[str] = None
    cv_filename: Optional[str]
    cv_parsed_at: Optional[datetime]
    # LinkedIn employment tracking (Phase: LinkedIn sync)
    linkedin_current_company: Optional[str] = None
    linkedin_current_title: Optional[str] = None
    linkedin_current_started_at: Optional[date] = None
    linkedin_employment_changed_at: Optional[datetime] = None
    linkedin_synced_at: Optional[datetime] = None
    linkedin_sync_status: LinkedinSyncStatus = LinkedinSyncStatus.disabled
    linkedin_sync_error: Optional[str] = None
    # Eager-loaded by `_candidate_list_options()` to avoid MissingGreenlet
    # under Pydantic's from_attributes. Detail endpoint trims to the 5 most
    # recent; list endpoint strips to None to keep list responses small.
    linkedin_snapshots: Optional[List[LinkedinSnapshotSummary]] = None
    # Phase D4: AI-extracted CV data (companies, career_summary, _source tag,
    # manual-override flag). Surfaced to the frontend so the profile view can
    # render "Firmy z CV" / "Podsumowanie AI" sections without a second fetch.
    cv_extracted_data: Optional[Any] = None
    notes_count: int
    last_contacted_at: Optional[datetime]
    embedding_id: Optional[str]
    # External-source attribution (Faza A migracji Traffit). Frontend używa
    # tego do badge "z Traffita" w nagłówku profilu kandydata.
    external_source: Optional[str] = None
    external_id: Optional[str] = None
    created_by: Optional[int] = None
    # Reads from ORM attribute `creator` (Candidate.creator relationship).
    # Populated when the endpoint eager-loads `selectinload(Candidate.creator)`.
    created_by_user: Optional[CandidateCreatorBrief] = Field(
        default=None, validation_alias="creator"
    )
    created_at: datetime
    updated_at: datetime
    # Phase A1: populated only when list endpoint is called with include_match_stats=true
    match_stats: Optional[MatchStats] = None
    # Phase: Snippet highlights (Traffit parity follow-up). Populated when
    # the list endpoint is called with a search phrase (`q`, `q_all`, or
    # `q_any`); otherwise None. The string already includes the field-of-
    # origin prefix ("CV:", "Notatka:", …) — frontend renders it verbatim
    # and applies <mark> highlighting client-side.
    match_snippet: Optional[str] = None
    # Talent pools the candidate belongs to. Populated when the list endpoint
    # eager-loads `pool_memberships → pool` (see `_candidate_list_options`).
    talent_pools: list[TalentPoolBrief] = Field(default_factory=list)
    # Aktywne rekrutacje kandydata (najnowszy stage per job, stage NOT IN
    # {rejected, withdrawn, hired}). Populated TYLKO przez list endpoint
    # z parametrem `include_active_recruitments=true` (osobny lekki query).
    active_recruitments: Optional[list[ActiveRecruitmentBrief]] = None
    # Quick-glance triage fields (Phase „Search inline visibility").
    # Populated TYLKO gdy list endpoint dostanie `include_last_activity=true`.
    # Trzy DISTINCT ON-style query'sy per page; brak N+1.
    last_note_preview: Optional[str] = None
    last_rejection_reason: Optional[str] = None
    last_rate: Optional[str] = None
    # Populated only by GET /candidates/{id} — latest invite-link apply event
    # resolved to label + recruiter name (+ previous owner if transferred).
    invite_source: Optional[InviteSourceBrief] = None

    model_config = {"from_attributes": True, "populate_by_name": True}


class CandidateQuickViewPosition(BaseModel):
    title: Optional[str] = None
    started_at: Optional[str] = None
    precision: Literal["date", "month", "year", "unknown"] = "unknown"


class CandidateQuickViewAvailability(BaseModel):
    status: AvailabilityStatus = AvailabilityStatus.unknown
    available_from: Optional[date] = None
    notice_period: Optional[int] = None
    notice_period_unit: Optional[Literal["days", "weeks", "months"]] = None


class CandidateQuickViewSource(BaseModel):
    added_by_name: str
    acquisition_source: Optional[str] = None
    imported_via: Optional[str] = None


class CandidateQuickViewRecruitment(BaseModel):
    job_id: int
    job_title: str
    client_name: Optional[str] = None
    stage_id: int
    stage_name: str
    moved_at: datetime
    moved_by_name: Optional[str] = None


class CandidateQuickViewNote(BaseModel):
    id: int
    content: str
    created_at: datetime
    author_name: Optional[str] = None


class CandidateCvHighlights(BaseModel):
    profile: Optional[str] = None
    years_experience: Optional[int] = None
    current_role: Optional[str] = None
    current_role_started_at: Optional[str] = None
    current_role_started_at_precision: Literal["date", "month", "year", "unknown"] = (
        "unknown"
    )
    technologies: list[str] = Field(default_factory=list)
    sectors: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list, max_length=4)
    source_document_id: Optional[int] = None
    source_hash: Optional[str] = None
    extractor_version: Optional[str] = None
    generated_at: Optional[datetime] = None


class CandidateQuickViewCapabilities(BaseModel):
    can_assign: bool
    can_mark_employed: bool
    can_view_documents: bool
    can_open_full_profile: bool


class CandidateQuickViewCandidate(BaseModel):
    """Minimal candidate identity used by the quick-view drawer.

    Deliberately excludes ``cv_extracted_data`` and all other full-profile
    fields so this bounded endpoint never transports CV content.
    """

    id: int
    name: str
    lastname: str
    email: Optional[str] = None
    phone: Optional[str] = None
    city: Optional[str] = None
    location: Optional[str] = None
    status: CandidateStatus
    employment: EmploymentInfo = EmploymentInfo(state=EmploymentState.unknown)
    competence_category_id: Optional[int] = None
    competence_category: Optional[str] = None
    skills: Optional[Any] = None


class CandidateQuickViewResponse(BaseModel):
    candidate: CandidateQuickViewCandidate
    current_position: CandidateQuickViewPosition
    availability: CandidateQuickViewAvailability
    source: CandidateQuickViewSource
    current_recruitments: list[CandidateQuickViewRecruitment] = Field(
        default_factory=list
    )
    recent_notes: list[CandidateQuickViewNote] = Field(default_factory=list)
    cv_highlights: CandidateCvHighlights
    capabilities: CandidateQuickViewCapabilities


class CandidateList(BaseModel):
    items: list[CandidateResponse]
    total: int
    page: int
    page_size: int


class CandidateFromCVDuplicate(BaseModel):
    """One duplicate candidate found during /from-cv dedup scan."""

    candidate_id: int
    name: Optional[str] = None
    lastname: Optional[str] = None
    email: Optional[str] = None
    match_score: float
    match_reasons: list[str] = Field(default_factory=list)


class CandidateFromCVResponse(BaseModel):
    """Response for POST /candidates/from-cv.

    The `candidate` field carries the newly-created profile exactly like the
    standard CandidateResponse. `confidence` mirrors the LLM's per-field
    certainty so the UI can flag low-confidence values for manual review.
    `duplicates` is populated (non-empty) only when the endpoint is called
    with `?force=true` despite existing matches — the default flow returns
    HTTP 409 instead.
    """

    candidate: CandidateResponse
    confidence: dict[str, float] = Field(default_factory=dict)
    duplicates: list[CandidateFromCVDuplicate] = Field(default_factory=list)
    source: Optional[str] = None  # e.g. "claude:cv_enrichment:v4"


class CandidateFromCVConflictResponse(BaseModel):
    """409 response when a duplicate is found during /from-cv."""

    detail: str
    existing_candidate_id: int
    matches: list[CandidateFromCVDuplicate]


class CandidateDocumentOut(BaseModel):
    """Pojedynczy plik kandydata (multi-file CV) — list response.

    Nie zawiera `file_content` (BYTEA) — pobiera się osobno przez
    `/api/candidates/{id}/documents/{doc_id}/content` endpoint.
    """

    id: int
    filename: str
    content_type: Optional[str] = None
    size_bytes: Optional[int] = None
    document_kind: Literal["cv", "cover_letter", "certificate", "other"]
    is_primary: bool
    uploaded_at: Optional[datetime] = None
    external_source: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateDocumentUpdate(BaseModel):
    document_kind: Optional[Literal["cv", "cover_letter", "certificate", "other"]] = (
        None
    )
    is_primary: Optional[bool] = None


# ── Chrome extension: POST /api/candidates/from-linkedin ────────────────────


class LinkedInPreview(BaseModel):
    """Lightly scraped preview from the LinkedIn profile DOM.

    Used to populate the candidate stub immediately (so the user sees a usable
    record while Proxycurl enrichment runs in the background). All fields are
    nullable — the server treats Proxycurl as the authoritative source and will
    overwrite these within minutes.
    """

    name: Optional[str] = Field(default=None, max_length=100)
    lastname: Optional[str] = Field(default=None, max_length=100)
    headline: Optional[str] = Field(default=None, max_length=255)
    location: Optional[str] = Field(default=None, max_length=255)
    current_company: Optional[str] = Field(default=None, max_length=255)


class CandidateFromLinkedInCreate(BaseModel):
    """Payload from the NEXUS Chrome extension on a LinkedIn profile page."""

    linkedin_url: str = Field(..., min_length=1, max_length=500)
    preview: Optional[LinkedInPreview] = None
    tags: Optional[List[str]] = None
    notes: Optional[str] = Field(default=None, max_length=4000)
    job_id: Optional[int] = None
    stage: Optional[PipelineStage] = (
        None  # default applied in handler: PipelineStage.new
    )


class CandidateFromLinkedInResponse(BaseModel):
    """Response shape consumed by the extension popup.

    ``action`` is the discriminator the popup uses to switch between the
    "Dodano X" toast and the "Już w bazie — odśwież?" UI. ``profile_url_path``
    is appended to the frontend base URL by the extension (it doesn't know the
    NEXUS frontend hostname — that's a settings concern).
    """

    action: Literal["created", "existing"]
    candidate_id: int
    name: str
    linkedin_url: str
    linkedin_sync_status: LinkedinSyncStatus
    assigned_to_job_id: Optional[int] = None
    profile_url_path: str
    resync_scheduled: bool = False
