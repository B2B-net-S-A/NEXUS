"""Schemas for stage-specific scorecards (Phase 3)."""

from typing import Any, List, Literal, Optional

from pydantic import BaseModel, Field


class ScorecardQuestion(BaseModel):
    """One question in a stage scorecard definition."""

    id: str = Field(..., description="Stable key — used in answers map")
    label: str
    type: Literal["rating", "text", "checkbox", "select"]
    options: Optional[List[str]] = None  # for select
    required: bool = False
    description: Optional[str] = None


class ScorecardSchema(BaseModel):
    """Structure stored in PipelineStageDef.scorecard_schema (JSONB)."""

    title: Optional[str] = None
    questions: List[ScorecardQuestion] = Field(default_factory=list)


class ScorecardAnswer(BaseModel):
    """One answer for a scorecard question."""

    question_id: str
    value: Any  # int (1-5), bool, str, or list for select


class ScorecardSubmission(BaseModel):
    """Payload from UI when submitting a scorecard alongside a stage move."""

    stage_id: int  # CandidateStage.id
    stage_def_id: int  # PipelineStageDef.id (where the schema lives)
    answers: List[ScorecardAnswer]
    overall_rating: Optional[int] = Field(None, ge=1, le=5)
    notes: Optional[str] = None
