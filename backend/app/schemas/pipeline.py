from datetime import datetime
from decimal import Decimal
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.candidate_risk import CandidateOfferResponse
from app.models.contract import RateUnit
from app.models.recruitment_pipeline import (
    PipelineStage,
    StageCategory,
    VerificationStatus,
)
from app.schemas.candidate_contact import ContactCaseSummaryResponse


class StageMove(BaseModel):
    """Payload for moving a candidate to a new stage.

    Phase 1 accepts EITHER `stage` (legacy enum, resolved via default template
    legacy_enum_value) OR `stage_def_id` (new FK). At least one is required.
    Terminal moves (rejected/withdrawn) should include `rejection_reason_id`.
    """

    candidate_id: int
    job_id: int
    stage: Optional[PipelineStage] = None
    stage_def_id: Optional[int] = None
    notes: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    rejection_reason_id: Optional[int] = None
    rejection_reason: Optional[str] = None  # legacy free-text — kept for BC

    # Automatic rejection-email scheduling (0045_rejection_emails):
    # None → let the server decide based on previous_stage (default: on for
    #        client-visible stages, off otherwise).
    # True  → attempt scheduling (still gated by server-side eligibility).
    # False → do NOT schedule, even if eligible.
    send_rejection_email: Optional[bool] = None
    # Optional override — use a specific EmailTemplate.id instead of the
    # default rejection template.
    rejection_email_template_id: Optional[int] = None

    # ── Pending verification (migracja 0056) ──────────────────────────────
    # Wymagane TYLKO przy ruchu na stage `verified` — recruiter podaje stawkę
    # kandydata którą porównujemy z Job.salary_max. Jeśli rate > max → stage
    # zapisany z verification_status='pending', wysyłka notif do approverów.
    expected_rate_value: Optional[Decimal] = Field(None, ge=0)
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = Field(None, max_length=3)

    # ── Candidate offer response (migracja 0066 — Phase 17) ───────────────
    # Sensowne tylko gdy stage ∈ {acceptance, negotiation, onboarding}.
    # `declined` przed wycofaniem → post_accept dropout (10pt w risk score).
    candidate_offer_response: Optional[CandidateOfferResponse] = None


class ClientRateUpdate(BaseModel):
    """Body dla PATCH /candidates/{id}/recruitments/{job_id}/client-rate.

    Ustawia „Stawkę do klienta" (sell rate) dla danej rekrutacji.
    `rate_value=None` → wyczyść stawkę. Gdy podana wartość bez jednostki,
    backend domyślnie przyjmuje `monthly`.
    """

    rate_value: Optional[Decimal] = Field(None, ge=0)
    rate_unit: Optional[RateUnit] = None
    rate_currency: Optional[str] = Field(default="PLN", max_length=3)


class HiringManagerVetoBrief(BaseModel):
    """A standing rejection by the hiring manager of the job being viewed."""

    hiring_manager_contact_id: int
    hiring_manager_name: Optional[str] = None
    source_job_id: int
    source_job_title: Optional[str] = None
    rejected_at: datetime
    rejection_reason_name: str
    rejection_note: Optional[str] = None


class CandidateStageResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    stage: PipelineStage
    stage_def_id: Optional[int] = None
    rejection_reason_id: Optional[int] = None
    moved_at: datetime
    moved_by: Optional[int]
    notes: Optional[str]
    rating: Optional[int]
    created_at: datetime
    days_in_stage: Optional[int] = None
    # Candidate name/lastname — populated by Kanban endpoint to render card titles.
    name: Optional[str] = None
    lastname: Optional[str] = None
    # Who assigned this candidate to the recruitment (= mover on the EARLIEST
    # CandidateStage of this candidate/job pair) and when. Populated by the
    # Kanban endpoint so cards can show "kto przypisał kandydata do rekrutacji"
    # on hover. Distinct from `moved_by` which is the current-stage mover.
    added_to_job_by_name: Optional[str] = None
    added_to_job_at: Optional[datetime] = None
    # Set when this move caused a rejection email to be queued; lets the FE
    # show a "Cofnij wysyłkę" toast and anchor the cancel link.
    scheduled_rejection_email_id: Optional[int] = None
    # This job's hiring manager already rejected the candidate after an
    # interview elsewhere. Populated by the Kanban endpoint only — the manager
    # is implicit there (it is this job's), so the card needs no name, and the
    # recruiter learns *before* dragging the card rather than from a 409.
    hm_veto: Optional["HiringManagerVetoBrief"] = None
    contact_case: Optional[ContactCaseSummaryResponse] = None

    # ── Pending verification (migracja 0056) ──────────────────────────────
    verification_status: VerificationStatus = VerificationStatus.active
    expected_rate_value: Optional[Decimal] = None
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = None
    budget_max_at_move: Optional[int] = None
    approved_by: Optional[int] = None
    approved_at: Optional[datetime] = None
    rejected_by: Optional[int] = None
    rejected_at: Optional[datetime] = None
    rejection_note: Optional[str] = None

    model_config = {"from_attributes": True}


class PendingVerificationReject(BaseModel):
    """Body dla POST /pipeline/{stage_id}/reject-verification.

    `note` jest wymagana, żeby recruiter zobaczył dlaczego zostało odrzucone
    (trafia do notatki nowego CandidateStage z poprzednim stage'em).
    """

    note: str = Field(..., min_length=1, max_length=1000)


class PendingVerificationListItem(BaseModel):
    """Wiersz listy /pipeline/pending-verifications dla approverów."""

    candidate_stage_id: int
    candidate_id: int
    candidate_name: str
    job_id: int
    job_title: str
    expected_rate_value: Optional[Decimal] = None
    expected_rate_unit: Optional[RateUnit] = None
    expected_rate_currency: Optional[str] = None
    budget_max_at_move: Optional[int] = None
    # M4 PR-02 (audyt P0.5): approver widzi porównanie w JEDNEJ jednostce —
    # stawka znormalizowana do PLN/mc (168h/21d) albo None + nota, czemu
    # wymagany jest manual review (waluta ≠ PLN / nieznana jednostka).
    normalized_monthly_value: Optional[Decimal] = None
    normalization_note: Optional[str] = None
    moved_at: datetime
    moved_by: Optional[int] = None
    moved_by_name: Optional[str] = None
    notes: Optional[str] = None

    model_config = {"from_attributes": True}


class KanbanColumn(BaseModel):
    stage: PipelineStage
    category: StageCategory
    count: int
    items: List[CandidateStageResponse]
    # Phase 1 additions (optional, BC)
    stage_def_id: Optional[int] = None
    name: Optional[str] = None
    order: Optional[int] = None
    # KTÓRY terminal, nie tylko „czy terminal".
    #
    # `stage` dla kolumny bez mapowania na legacy enum degraduje do `new`, a
    # `category` mówi najwyżej „terminal". Frontend rozpoznawał hired/rejected/
    # withdrawn po `stage`, więc dla WŁASNEGO etapu terminalnego:
    #   - „odrzucony" nie otwierał modala powodu → backend odbijał 422,
    #   - „zatrudniony" pomijał potwierdzenie, mimo że backend i tak uruchamiał
    #     skutki uboczne (draft kontraktu + zamówienie klienta).
    # To pole niesie tę informację wprost. Pozostaje opcjonalne — kolumny
    # nieterminalne mają `None`.
    terminal_type: Optional[Literal["hired", "rejected", "withdrawn"]] = None


class KanbanView(BaseModel):
    job_id: int
    columns: List[KanbanColumn]


class StageInfo(BaseModel):
    stage: PipelineStage
    category: StageCategory
    label: str
    order: int
    # Phase 1: new elastic fields (None for the synthetic terminal stages)
    stage_def_id: Optional[int] = None
    is_terminal: bool = False


# Polish labels for all stages
STAGE_LABELS: dict[PipelineStage, str] = {
    PipelineStage.new: "Nowi / Analiza CV",
    PipelineStage.prep_call: "Preparation Call",
    PipelineStage.screening: "Screening",
    PipelineStage.verified: "Zweryfikowany",
    PipelineStage.interview: "Interview Wewnętrzny",
    PipelineStage.cv_sent: "CV Wysłane",
    PipelineStage.client_interview: "Interview Klient",
    PipelineStage.acceptance: "Akceptacja",
    PipelineStage.negotiation: "Negocjacje",
    PipelineStage.onboarding: "Onboarding",
    PipelineStage.hired: "Zatrudniony",
    PipelineStage.rejected: "Odrzucony",
    PipelineStage.withdrawn: "Wycofany",
}
