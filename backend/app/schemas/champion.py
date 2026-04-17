"""Pydantic schemas for the Champion Profile (Phase 10).

Mirrors the Delivery Lead's "Profil Championa" Word template.
Stored as JSONB inside `jobs.champion_profile` so we avoid a dedicated table
for a document-shaped payload that only the Delivery Lead owns.
"""

from __future__ import annotations

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field


# ── Building blocks ──────────────────────────────────────────────────────────


class ChampionBasics(BaseModel):
    """Extra role metadata not captured by existing Job columns."""

    onsite_days_per_week: Optional[int] = Field(default=None, ge=0, le=7)
    candidate_location_pref: Optional[str] = Field(default=None, max_length=255)
    language: Optional[str] = Field(default=None, max_length=50)


class ChampionProjectContext(BaseModel):
    """Narrative context the recruiter uses when pitching to candidates."""

    about: str = ""
    responsibilities: str = ""
    selling_points: str = ""


class ScreeningQuestion(BaseModel):
    """One DL-authored screening question with grading hints."""

    id: str = Field(min_length=1, max_length=40)
    question: str = Field(min_length=1)
    ideal_answer: str = ""
    deal_breaker: str = ""


class SourcingStrategy(BaseModel):
    """Where / how to source. UI checkboxes + free-text notes."""

    sources: List[Literal["internal_base", "linkedin", "ad", "referrals", "other"]] = (
        Field(default_factory=list)
    )
    keywords: str = ""
    target_companies: str = ""
    notes: str = ""


# ── Full profile ─────────────────────────────────────────────────────────────


class ChampionProfile(BaseModel):
    basics: ChampionBasics = ChampionBasics()
    project_context: ChampionProjectContext = ChampionProjectContext()
    screening_questions: List[ScreeningQuestion] = Field(default_factory=list)
    historical_client_questions: str = ""
    internal_consultant_insight: str = ""
    sourcing: SourcingStrategy = SourcingStrategy()

    def is_screening_ready(self) -> bool:
        """True if there is at least one question — i.e. recruiter can be asked to screen."""
        return bool(self.screening_questions)


# ── Screening answers (CandidateStage.screening_answers) ────────────────────


class ScreeningAnswerItem(BaseModel):
    question_id: str
    response: str = ""
    deal_breaker_hit: bool = False


class ScreeningAnswers(BaseModel):
    """Full payload a recruiter submits when moving a candidate past screening."""

    answers: List[ScreeningAnswerItem] = Field(default_factory=list)
    overall_fit: Literal["fit", "uncertain", "miss"] = "uncertain"
    notes: str = ""
    answered_at: Optional[datetime] = None
    answered_by: Optional[int] = None

    def match_percent(self) -> float:
        """Return 0-100 approximation of how well the candidate aligns with the Champion.

        - 100 when overall_fit=fit and no deal_breaker_hit
        -   0 when any deal_breaker_hit is True
        - otherwise proportional to (answered questions / total) with
          `uncertain` → 0.6 and `fit` → 1.0 multiplier.
        """
        if any(a.deal_breaker_hit for a in self.answers):
            return 0.0
        if not self.answers:
            return 0.0
        answered = sum(1 for a in self.answers if a.response.strip())
        ratio = answered / max(len(self.answers), 1)
        fit_weight = {"fit": 1.0, "uncertain": 0.6, "miss": 0.2}[self.overall_fit]
        return round(ratio * fit_weight * 100.0, 1)
