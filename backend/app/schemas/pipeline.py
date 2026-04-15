from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field

from app.models.recruitment_pipeline import PipelineStage, StageCategory, STAGE_CATEGORY, STAGE_ORDER


class StageMove(BaseModel):
    """Payload for moving a candidate to a new stage."""
    candidate_id: int
    job_id: int
    stage: PipelineStage
    notes: Optional[str] = None
    rating: Optional[int] = Field(None, ge=1, le=5)
    rejection_reason: Optional[str] = None


class CandidateStageResponse(BaseModel):
    id: int
    candidate_id: int
    job_id: int
    stage: PipelineStage
    moved_at: datetime
    moved_by: Optional[int]
    notes: Optional[str]
    rating: Optional[int]
    created_at: datetime
    days_in_stage: Optional[int] = None

    model_config = {"from_attributes": True}


class KanbanColumn(BaseModel):
    stage: PipelineStage
    category: StageCategory
    count: int
    items: List[CandidateStageResponse]


class KanbanView(BaseModel):
    job_id: int
    columns: List[KanbanColumn]


class StageInfo(BaseModel):
    stage: PipelineStage
    category: StageCategory
    label: str
    order: int


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
