from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel

from app.models.contract import (
    ContractStatus,
    ContractTerminationReason,
    ContractType,
    ContractWorkMode,
    EngagementModel,
    OrderConsumptionUnit,
    ProlongationStatus,
    RateUnit,
)


class ContractCandidateRateInput(BaseModel):
    """One step in the candidate-rate schedule sent from a create/edit form.

    ``effective_to`` ("Obowiązuje do") is the optional planned end of the step,
    used by the "stawka progresywna" editor; it is advisory (see the model).
    """

    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None


class ContractCandidateRateEntry(BaseModel):
    """One step in the candidate-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractClientRateEntry(BaseModel):
    """One step in the client-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractFrameworkRateInput(BaseModel):
    """One step in the framework-rate schedule sent from a create/edit form.

    ``effective_to`` ("Obowiązuje do") is the optional planned end of the step;
    it is advisory (see the model). Mirrors ``ContractCandidateRateInput``.
    """

    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None


class ContractFrameworkRateEntry(BaseModel):
    """One step in the framework-rate schedule returned to the client."""

    id: int
    rate: float
    effective_from: date
    effective_to: Optional[date] = None
    note: Optional[str] = None
    created_by: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractCreate(BaseModel):
    candidate_id: int
    client_id: int
    job_id: Optional[int] = None
    start_date: date
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    # `float`, NIE `int` — stawki ramowe/widełki bywają z groszami (np. 215,60);
    # Pydantic `int` odrzuca część ułamkową 422-ką zamiast zaokrąglić.
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: str = "PLN"
    rate_unit: RateUnit = RateUnit.monthly
    billing_hours_per_month: int = 160
    # Effective-dated candidate-rate schedule (optional). When provided, drives
    # the candidate rate over time; `rate_candidate` is derived from it.
    candidate_rate_schedule: Optional[list[ContractCandidateRateInput]] = None
    # Effective-dated framework-rate schedule (optional). When provided, drives
    # the framework rate over time; `framework_rate` is derived from it.
    framework_rate_schedule: Optional[list[ContractFrameworkRateInput]] = None
    contract_type: ContractType = ContractType.b2b
    # `status` is intentionally NOT accepted here. A contract is always born a
    # `draft`; reaching `active` is guarded by ``contract_lifecycle`` (requires
    # signed evidence). Any `status` in the request body is ignored server-side.
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    # Per-klient rejestr (migracja 0138)
    project_code: Optional[str] = None
    prolongation_status: ProlongationStatus = ProlongationStatus.unknown
    engagement_model: EngagementModel = EngagementModel.time_based
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — ilość + jednostka RBH/MD.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None


class ContractUpdate(BaseModel):
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    # Effective-dated candidate-rate schedule ("stawka progresywna"). When the
    # key is present the endpoint REPLACES the whole schedule with these steps
    # and re-derives `rate_candidate` from them; omit the key to leave the
    # existing schedule untouched (backward-compatible for partial PATCHes).
    candidate_rate_schedule: Optional[list[ContractCandidateRateInput]] = None
    # Effective-dated framework-rate schedule ("stawka z umowy ramowej"). When the
    # key is present the endpoint REPLACES the whole schedule with these steps and
    # re-derives `framework_rate` from them; omit the key to leave the existing
    # schedule untouched (backward-compatible for partial PATCHes).
    framework_rate_schedule: Optional[list[ContractFrameworkRateInput]] = None
    # `float`, NIE `int` — grosze (215,60) w stawce ramowej/widełkach (jak wyżej).
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: Optional[str] = None
    rate_unit: Optional[RateUnit] = None
    billing_hours_per_month: Optional[int] = None
    contract_type: Optional[ContractType] = None
    # `status` is intentionally NOT accepted here — free status writes are the
    # bug this hardening closes. Status changes go through the dedicated
    # lifecycle endpoints (`/activate`, `/reopen`, `/void`, `/terminate`,
    # `/draft/finalize`). Any `status` in the request body is ignored.
    documents: Optional[Any] = None
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None
    # Per-klient rejestr (migracja 0138) — wszystkie opcjonalne dla PATCH.
    project_code: Optional[str] = None
    prolongation_status: Optional[ProlongationStatus] = None
    engagement_model: Optional[EngagementModel] = None
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — opcjonalne dla PATCH.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None


class ContractResponse(BaseModel):
    id: int
    candidate_id: int
    client_id: int
    job_id: Optional[int]
    start_date: Optional[date] = None
    end_date: Optional[date]
    client_order_end_date: Optional[date] = None
    rate_candidate: Optional[float]
    rate_client: Optional[float]
    framework_rate: Optional[float] = None
    target_rate_min: Optional[float] = None
    target_rate_max: Optional[float] = None
    currency: str
    rate_unit: RateUnit
    billing_hours_per_month: int
    margin: Optional[float]
    # Effective-dated candidate-rate schedule (oldest → newest). Empty for
    # contracts created before the schedule feature.
    candidate_rate_schedule: list[ContractCandidateRateEntry] = []
    # Effective-dated client-rate schedule (oldest → newest). Empty until a
    # `rate_change` amendment first defers the client rate to a future date.
    client_rate_schedule: list[ContractClientRateEntry] = []
    # Effective-dated framework-rate schedule (oldest → newest). Empty for
    # contracts without a planned framework-rate change (the common case).
    framework_rate_schedule: list[ContractFrameworkRateEntry] = []
    contract_type: ContractType
    status: ContractStatus
    documents: Optional[Any]
    client_pm_name: Optional[str] = None
    client_pm_email: Optional[str] = None
    line_manager: Optional[str] = None
    work_mode: Optional[ContractWorkMode] = None
    office_location: Optional[str] = None
    team_name: Optional[str] = None
    project_name: Optional[str] = None
    handover_notes: Optional[str] = None
    termination_reason: Optional[ContractTerminationReason] = None
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None
    # Per-klient rejestr (migracja 0138)
    project_code: Optional[str] = None
    prolongation_status: ProlongationStatus = ProlongationStatus.unknown
    engagement_model: EngagementModel = EngagementModel.time_based
    hours_pool_total: Optional[int] = None
    hours_pool_consumed: Optional[int] = None
    # Zużycie zamówienia (migracja 0144) — ilość + jednostka RBH/MD.
    order_consumption: Optional[float] = None
    order_consumption_unit: Optional[OrderConsumptionUnit] = None
    # Computed (model properties) — pozostałe godziny i % zużycia puli.
    hours_pool_remaining: Optional[int] = None
    hours_pool_usage_pct: Optional[float] = None
    # Draft body provenance (migracja 0058) — `content_html` itself is fetched
    # via the dedicated /draft endpoint to keep list payloads small.
    draft_template_id: Optional[int] = None
    draft_updated_at: Optional[datetime] = None
    draft_updated_by: Optional[int] = None
    created_at: datetime
    updated_at: datetime
    # Denormalized names — populated when relations are eager-loaded.
    candidate_name: Optional[str] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    # DL Portal refactor 2026-05-11: data końca aktualnego zamówienia klienta.
    # Z `Contract.client_orders` — najnowszy Order po end_date. Różny semantycznie
    # od `Contract.end_date` (umowa B2B z konsultantem, zwykle dłuższa) vs
    # `latest_order_end_date` (PDF od klienta, zwykle krótszy horyzont 3-6mc).
    latest_order_end_date: Optional[date] = None

    model_config = {"from_attributes": True}


class ContractTerminateRequest(BaseModel):
    """Payload dla dedykowanego POST /{id}/terminate."""

    termination_reason: ContractTerminationReason
    termination_lessons: Optional[str] = None
    terminated_at: Optional[date] = None  # default = today


class ContractBenchmarkComparison(BaseModel):
    """Porównanie stawki kontraktu vs nasza średnia vs rynek."""

    contract_rate_monthly: Optional[int] = None
    internal_avg_monthly: Optional[int] = None
    internal_median_monthly: Optional[int] = None
    internal_sample_size: int = 0
    market_min: Optional[int] = None
    market_median: Optional[int] = None
    market_max: Optional[int] = None
    market_source: Optional[str] = None
    market_source_date: Optional[date] = None
    role_used: Optional[str] = None
    currency: str = "PLN"


class ContractTimelineItem(BaseModel):
    """Połączony feed notes+calls per kontrakt (timeline)."""

    id: int
    kind: str  # "note" | "call"
    at: datetime
    summary: Optional[str] = None
    content: Optional[str] = None
    sub_type: Optional[str] = None  # note_type lub direction
    status: Optional[str] = None
    author_id: Optional[int] = None
    author_name: Optional[str] = None
    duration_seconds: Optional[int] = None

    model_config = {"from_attributes": True}


class ContractList(BaseModel):
    items: list[ContractResponse]
    total: int
    page: int
    page_size: int


class ContractDetailResponse(ContractResponse):
    """Extended response for the contract detail page — includes denormalized names."""

    candidate_name: Optional[str] = None
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    monthly_rate_candidate: Optional[float] = None
    monthly_rate_client: Optional[float] = None
    monthly_margin: Optional[float] = None

    model_config = {"from_attributes": True}


class ContractActivityEntry(BaseModel):
    id: int
    action: str
    details: Optional[Any] = None
    user_id: Optional[int] = None
    user_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ContractRateHistoryEntry(BaseModel):
    id: int
    # ``None`` when redacted for non-VIEW_FINANCE readers (P0.12) — the amount is
    # the sensitive field; ``currency`` stays as metadata.
    rate: Optional[float] = None
    currency: str
    contract_type: str
    start_date: date
    end_date: Optional[date] = None
    notes: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Contractor module ────────────────────────────────────────────────────────
# These schemas back the `/api/contractors` router and the new draft→active
# activation endpoint. The contractor view aggregates Contracts with status
# IN (draft, active, ending); drafts are exposed separately as "do uzupełnienia".


class ContractActivateRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/activate.

    Empty body — the assumption is that the client has already PATCH-ed the
    contract with the required fields. The activation endpoint only validates
    and flips the status. A future iteration may accept inline field updates
    here to collapse PATCH+activate into one call.
    """


class ContractReopenRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/reopen — audited revert to `draft`.

    Replaces the removed free ``PATCH {status: draft}`` write. The optional
    reason is recorded in the audit trail.
    """

    reason: Optional[str] = None


class ContractVoidRequest(BaseModel):
    """Payload for POST /api/contracts/{id}/void — soft-delete (annul).

    Used instead of a hard DELETE for executed/active contracts so documents and
    signature evidence are preserved.
    """

    reason: Optional[str] = None


# ── Editable draft (migracja 0058) ───────────────────────────────────────


class ContractTemplateBrief(BaseModel):
    """Minimal template descriptor returned with the draft so the FE can
    render the "Wybierz szablon" dropdown without a second roundtrip."""

    id: int
    name: str
    contract_type: str
    is_default: bool

    model_config = {"from_attributes": True}


class ContractDraftResponse(BaseModel):
    """Full draft state for the editor."""

    contract_id: int
    content_html: Optional[str] = None
    template_id: Optional[int] = None
    updated_at: Optional[datetime] = None
    updated_by: Optional[int] = None
    updated_by_name: Optional[str] = None
    available_templates: list[ContractTemplateBrief] = []
    # When True the FE knows it should warn the user that no default template
    # is configured for this contract_type and it has to pick one manually.
    rendered_from_default: bool = False


class ContractDraftUpdate(BaseModel):
    """Partial update — either swap the template (re-render) OR save edited
    HTML, never both at once. Validated in the endpoint."""

    template_id: Optional[int] = None
    content_html: Optional[str] = None


class ContractDraftFinalizeResponse(BaseModel):
    """Result of POST /{id}/draft/finalize."""

    contract_id: int
    status: ContractStatus
    document_id: Optional[int] = None
    document_filename: Optional[str] = None


class ContractorCandidateRef(BaseModel):
    id: int
    name: str
    lastname: str
    email: Optional[str] = None


class ContractorListItem(BaseModel):
    """Single row in the Contractors list view."""

    contract_id: int
    candidate: ContractorCandidateRef
    client_name: Optional[str] = None
    job_title: Optional[str] = None
    status: ContractStatus
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    rate_candidate: Optional[float] = None
    rate_client: Optional[float] = None
    rate_unit: RateUnit
    currency: str = "PLN"
    margin: Optional[float] = None
    contract_type: ContractType
    work_mode: Optional[ContractWorkMode] = None
    # Only populated for drafts — lists the required fields still missing
    # so the UI can badge the row ("3 braki") and skip the full detail fetch.
    missing_fields: list[str] = []


class ContractorList(BaseModel):
    items: list[ContractorListItem]
    total: int
    page: int
    page_size: int


class ContractorStats(BaseModel):
    """Counts for the admin dashboard widget + tab headers."""

    draft: int = 0
    drafts_incomplete: int = 0
    active: int = 0
    ending: int = 0
