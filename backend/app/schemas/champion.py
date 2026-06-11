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


# ── Two-sided verification ───────────────────────────────────────────────────
#
# The Champion Profile must not be a transcription of the client's request.
# The Delivery Lead verifies it from two sides: a conversation with the client
# (what do they REALLY need vs. what they wrote) and a conversation with one of
# our consultants already working at that client (what the day-to-day actually
# looks like). Soft signal only — publishing a job is never blocked on it.
#
# These blocks are server-stamped via POST /jobs/{id}/champion-profile/
# verification; a regular profile PUT preserves whatever is stored so the
# client cannot forge or wipe them.

VerificationMethod = Literal["call", "meeting", "email", "other"]


class ClientVerification(BaseModel):
    """Outcome of the DL ↔ client conversation about the request."""

    status: Literal["pending", "verified"] = "pending"
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    method: Optional[VerificationMethod] = None
    # Either the DL articulates what changed vs. the original request…
    key_corrections: str = ""
    # …or explicitly confirms the request was accurate as written.
    confirmed_as_is: bool = False


class ConsultantVerification(BaseModel):
    """Outcome of the DL ↔ our-consultant-at-the-client conversation."""

    status: Literal["pending", "verified", "skipped"] = "pending"
    verified_by_id: Optional[int] = None
    verified_by_name: Optional[str] = None
    verified_at: Optional[datetime] = None
    consultant_candidate_id: Optional[int] = None
    consultant_name: Optional[str] = None
    insights: str = ""
    # `skipped` escape hatch — no consultant placed at this client yet.
    skip_reason: str = ""


class ChampionVerification(BaseModel):
    client: ClientVerification = ClientVerification()
    consultant: ConsultantVerification = ConsultantVerification()

    def summary(self) -> Literal["none", "partial", "full"]:
        done = [
            self.client.status == "verified",
            self.consultant.status in ("verified", "skipped"),
        ]
        if all(done):
            return "full"
        if any(done):
            return "partial"
        return "none"


class ClientVerificationIn(BaseModel):
    """Payload the DL submits after talking to the client."""

    method: VerificationMethod = "call"
    key_corrections: str = ""
    confirmed_as_is: bool = False


class ConsultantVerificationIn(BaseModel):
    """Payload the DL submits after talking to our consultant (or skipping)."""

    consultant_candidate_id: Optional[int] = None
    consultant_name: str = ""
    insights: str = ""
    skipped: bool = False
    skip_reason: str = ""


class ChampionVerificationRequest(BaseModel):
    side: Literal["client", "consultant"]
    reset: bool = False
    client: Optional[ClientVerificationIn] = None
    consultant: Optional[ConsultantVerificationIn] = None


# ── DL briefing (breakout session) ───────────────────────────────────────────
#
# After the profile is verified, the DL records a short breakout session
# (Fireflies) explaining the role in their own words. The meeting Note is
# attached here so recruiters entering the job can listen to the audio and
# read the transcript instead of decoding a dry written profile. Server-
# stamped like `verification` — a profile PUT preserves the stored block.


class ChampionBriefing(BaseModel):
    status: Literal["pending", "attached"] = "pending"
    note_id: Optional[int] = None
    title: Optional[str] = None
    audio_storage_key: Optional[str] = None
    attached_by_id: Optional[int] = None
    attached_by_name: Optional[str] = None
    attached_at: Optional[datetime] = None


class ChampionBriefingRequest(BaseModel):
    note_id: int
    # Run LLM enrichment (cross-check briefing vs. profile) after attaching.
    enrich: bool = True


# ── Full profile ─────────────────────────────────────────────────────────────


class ChampionProfile(BaseModel):
    basics: ChampionBasics = ChampionBasics()
    project_context: ChampionProjectContext = ChampionProjectContext()
    screening_questions: List[ScreeningQuestion] = Field(default_factory=list)
    historical_client_questions: str = ""
    internal_consultant_insight: str = ""
    sourcing: SourcingStrategy = SourcingStrategy()
    verification: ChampionVerification = ChampionVerification()
    briefing: ChampionBriefing = ChampionBriefing()

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
