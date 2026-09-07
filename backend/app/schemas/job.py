from datetime import date, datetime
from typing import Literal, Any, List, Optional

from pydantic import BaseModel, Field, computed_field, field_validator

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
    # Budżet PLN/h dla kandydata (dealbreaker-switch; 0235).
    rate_budget_hourly: Optional[float] = Field(default=None, gt=0, le=2000)
    # 0278: bez domyślnej — „nieznane” jest stanem uczciwym, „hybrid” domyślne
    # kłamało dla każdej oferty, której nikt ręcznie nie ustawił.
    remote_policy: Optional[RemotePolicy] = None
    # Trzecia rubryka rekrutacji (obok must-have i rate_budget_hourly, 0278).
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    status: JobStatus = JobStatus.draft
    priority: JobPriority = JobPriority.medium
    needs_sourcing: bool = False
    recruitment_type: RecruitmentType = RecruitmentType.body_leasing
    deadline: Optional[date] = None
    # client_id: required od migracji 0120 (2026-05-27). NOT NULL na DB.
    # Tworzenie joba bez klienta zwraca 422 — orphan recordy nigdy nie wpadną
    # na listę /jobs (patrz QA sweep PR fix/qa-jobs-orphan-cleanup).
    client_id: int = Field(..., gt=0)
    recruiter_id: Optional[int] = None
    # TAC + Delivery Lead — jeśli podane jawnie, wygrywa nad auto-assignem.
    # Jawny TAC musi być przypisany do klienta; auto-assign TAC działa tylko
    # dla dokładnie jednego aktywnego przypisania klienta.
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    # Hiring manager — Contact w firmie klienta odpowiedzialny za rekrutację
    # (migracja 0097, 2026-05-11). Nullable, validated że należy do client_id.
    hiring_manager_contact_id: Optional[int] = None
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
    # Phase 15 / Phase D: programme / ART tag — free-text, optional.
    # Auto-populated by `extract_train_name` when left empty.
    train_name: Optional[str] = None

    # AI CC matching (migracja 0041). Jeśli `competence_category_id` podane —
    # używamy jawnie; jeśli None + `auto_suggest_cc=true` — classifier wybiera
    # top-1 (albo zostawia None gdy remis <0.10). `secondary_cc_ids` do wider
    # matchingu (max 2, validated w endpointzie).
    competence_category_id: Optional[int] = None
    secondary_cc_ids: Optional[List[int]] = None
    auto_suggest_cc: bool = True

    # "Skopiuj jako template" (zakładka Historia requestu). Gdy ustawione,
    # backend kopiuje brakujące pola (description / requirements / skills /
    # train_name / seniority / industry / subcategory / headcount / work_mode /
    # remote_policy / salary range) z source job, plus `champion_profile`
    # tylko gdy nowy job jest u tego samego klienta. Pola, które klient
    # wypełnił w formularzu, mają precedencję.
    from_job_id: Optional[int] = Field(default=None, gt=0)
    # Jeśli True i `from_job_id` ustawione — kopiujemy też pinned interview
    # questions (job_questions) z source job. Idempotent dzięki unique
    # constraint (job_id, question_id).
    copy_questions: bool = False

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
    # Budżet PLN/h dla kandydata (dealbreaker-switch; 0235).
    rate_budget_hourly: Optional[float] = Field(default=None, gt=0, le=2000)
    remote_policy: Optional[RemotePolicy] = None
    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    status: Optional[JobStatus] = None
    priority: Optional[JobPriority] = None
    needs_sourcing: Optional[bool] = None
    recruitment_type: Optional[RecruitmentType] = None
    deadline: Optional[date] = None
    client_id: Optional[int] = None
    recruiter_id: Optional[int] = None
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    hiring_manager_contact_id: Optional[int] = None
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
    # Phase 15 / Phase D: allow DL to set/override train_name explicitly.
    train_name: Optional[str] = None

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


class UserBrief(BaseModel):
    """Minimal user projection embedded in job owner/collaborator responses."""

    id: int
    email: str
    name: str
    role: Optional[str] = None
    roles: list[str] = Field(default_factory=list)

    model_config = {"from_attributes": True}

    @field_validator("role", mode="before")
    @classmethod
    def _role_to_str(cls, v: Any) -> Optional[str]:
        if v is None:
            return None
        return getattr(v, "value", str(v))


class JobResponse(BaseModel):
    id: int
    title: str
    description: Optional[str]
    requirements: Optional[str]
    location: Optional[str]
    salary_min: Optional[int]
    salary_max: Optional[int]
    rate_budget_hourly: Optional[float] = None
    # 0278: nullable — patrz komentarz w JobCreate.
    remote_policy: Optional[RemotePolicy] = None
    onsite_days_per_week: Optional[int] = None
    status: JobStatus
    # Czy rekrutacja jest aktywnie prowadzona w NEXUSIE (0270). NIE to samo co
    # `status`, który jest lustrem Traffita — patrz `models/job.py`.
    is_open: bool = False
    priority: JobPriority
    needs_sourcing: bool = False
    recruitment_type: RecruitmentType
    deadline: Optional[date]
    client_id: Optional[int]
    client_name: Optional[str] = None  # denormalized (coalesce(display_name, name))
    recruiter_id: Optional[int]
    tac_id: Optional[int] = None
    delivery_lead_id: Optional[int] = None
    hiring_manager_contact_id: Optional[int] = None
    hiring_manager_name: Optional[str] = None  # denormalized
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
    opened_at: Optional[datetime] = None
    closed_at: Optional[datetime] = None
    close_reason: Optional[JobCloseReason] = None
    close_notes: Optional[str] = None
    # Phase 15 / Phase D: programme tag surfaced to UI for autocomplete.
    train_name: Optional[str] = None
    # Hydrated ownership data added by api/jobs.get_job and assign/release
    # endpoints. ``primary_owner`` mirrors ``recruiter_id`` resolved to a
    # ``UserBrief`` so the UI does not need to do a second fetch to render the
    # owner badge. Both are ``None``/empty when the job is unassigned.
    primary_owner: Optional[UserBrief] = None
    collaborators: list[UserBrief] = []
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @computed_field
    @property
    def has_budget_hourly(self) -> bool:
        """Czy oferta ma ROZWIĄZYWALNY budżet PLN/h (jawne pole lub stawka
        Championa) — czyli czy sufit budżetowy ma na czym działać.

        Bool zamiast kwoty świadomie: `rate_budget_hourly` podlega redakcji
        finansowej dla viewera (`_VIEWER_REDACTED_JOB_FIELDS`), a UI potrzebuje
        wyłącznie informacji „jest co pilnować", żeby nie renderować aktywnego
        przełącznika, którego kliknięcie nic nie zmienia (review #1207).
        Liczone tą samą funkcją co filtr, więc nie może się z nim rozjechać.
        """
        from app.services.dealbreaker_filters import resolve_job_budget_hourly

        return resolve_job_budget_hourly(self) is not None


class JobList(BaseModel):
    items: list[JobResponse]
    total: int
    page: int
    page_size: int


class JobOwnerAssignment(BaseModel):
    """Set/change the primary owner (`jobs.recruiter_id`).

    Admin + Delivery Lead only. To clear the assignment use
    DELETE /api/jobs/{id}/owner instead — this payload requires a target user.
    """

    user_id: int


class JobCollaboratorAdd(BaseModel):
    """Add a collaborator (read-only participant) to a job."""

    user_id: int


class JobCloseRequest(BaseModel):
    """Payload for POST /jobs/{id}/close — records why the job was closed."""

    reason: JobCloseReason
    notes: Optional[str] = None


class JobHandoffRequest(BaseModel):
    """Payload for POST /jobs/{id}/handoff ("Przekaż do searchu").

    The Delivery Lead assigns the recruiter who will work the recruitment and
    starts the (Champion-aware) ranking. ``recruiter_id`` binds the recruiter as
    the job's owner for the pilot; the Priority Work roster is a later
    enhancement.
    """

    recruiter_id: Optional[int] = Field(default=None, gt=0)
    assignment_mode: Literal["manual", "automatic"] = "manual"
    channel: Literal["linkedin", "database", "mixed"] = "linkedin"
    top_k: Optional[int] = Field(default=None, gt=0)
