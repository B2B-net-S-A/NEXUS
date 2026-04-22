from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.recruitment_pipeline import PipelineStage, StageCategory


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
    # Set when this move caused a rejection email to be queued; lets the FE
    # show a "Cofnij wysyłkę" toast and anchor the cancel link.
    scheduled_rejection_email_id: Optional[int] = None

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
