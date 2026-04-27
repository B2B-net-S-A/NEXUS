"""Pydantic schemas for the Candidate Risk Profile feature.

See `app.models.candidate_risk` and migracja 0066_candidate_risk for the
underlying data model. Mirrors backend enums to allow direct serialization.
"""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.candidate_risk import RiskLevel


RiskCategory = Literal["early", "interview", "post_accept"]


class RiskBreakdown(BaseModel):
    """Liczność wycofań w 24-miesięcznym oknie per kategoria."""

    early: int = Field(0, ge=0, description="Wycofania przed jakimkolwiek interview")
    interview: int = Field(
        0, ge=0, description="Wycofania po wejściu w interview / cv_sent / client_interview"
    )
    post_accept: int = Field(
        0, ge=0, description="Wycofania po akcepcie oferty przez kandydata"
    )


class RiskEvent(BaseModel):
    """Pojedynczy dropout event w historii kandydata."""

    job_id: int
    moved_at: datetime
    category: RiskCategory
    reason: str
    job_title: Optional[str] = None


class CandidateRiskProfileOut(BaseModel):
    """Response payload dla GET /api/candidates/{id}/risk."""

    candidate_id: int
    level: RiskLevel
    score: int = Field(..., ge=0)
    breakdown: RiskBreakdown
    last_updated_at: datetime
    recent_events: List[RiskEvent] = Field(default_factory=list)
    profile_exists: bool = True

    model_config = {"from_attributes": True}
