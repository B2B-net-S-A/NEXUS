"""Pydantic schemas for Champion Profile AI suggestions (Phase 14)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.champion_suggestion import SuggestionSource, SuggestionStatus
from app.schemas.champion import ChampionProfile


# Section names that correspond to ChampionProfile top-level fields.
VALID_SECTIONS: tuple[str, ...] = (
    "basics",
    "project_context",
    "screening_questions",
    "historical_client_questions",
    "internal_consultant_insight",
    "sourcing",
)


# ── Input payloads ──────────────────────────────────────────────────────────


class GenerateFromJdPayload(BaseModel):
    """Request body for POST /jobs/{id}/champion-profile/generate-from-jd."""

    raw_description: str = Field(min_length=50, max_length=50_000)


class LinkNoteJobPayload(BaseModel):
    """Request body for POST /notes/{id}/link-job."""

    job_id: int = Field(gt=0)


class ApplyPayload(BaseModel):
    """Request body for POST /champion-suggestions/{id}/apply."""

    accepted_sections: List[str] = Field(default_factory=list)


# ── Output payloads ─────────────────────────────────────────────────────────


class SectionPatch(BaseModel):
    """One section's proposed value + confidence + optional rationale."""

    section: str
    value: Any = None
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    rationale: str = ""


class ChampionProfileSuggestionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    source_type: SuggestionSource
    source_ref: Optional[str] = None
    status: SuggestionStatus
    created_by_id: Optional[int] = None
    reviewed_by_id: Optional[int] = None
    created_at: datetime
    reviewed_at: Optional[datetime] = None
    model_name: Optional[str] = None
    prompt_version: Optional[int] = None
    error_message: Optional[str] = None

    patches: List[SectionPatch] = Field(default_factory=list)


class ChampionProfileSuggestionListOut(BaseModel):
    items: List[ChampionProfileSuggestionOut]
    total: int


# ── Helpers ─────────────────────────────────────────────────────────────────


def patches_from_payload(payload: dict[str, Any]) -> List[SectionPatch]:
    """Unpack the JSONB payload into a typed list of SectionPatch.

    Ignores sections that are not recognised (forward-compatible).
    """
    out: List[SectionPatch] = []
    for section in VALID_SECTIONS:
        entry = payload.get(section)
        if not isinstance(entry, dict):
            continue
        out.append(
            SectionPatch(
                section=section,
                value=entry.get("value"),
                confidence=float(entry.get("confidence") or 0.0),
                rationale=str(entry.get("rationale") or ""),
            )
        )
    return out


def payload_from_profile(
    profile: ChampionProfile, confidence: dict[str, float] | None = None
) -> dict[str, Any]:
    """Build a JSONB payload from a full ChampionProfile (used for JD parse).

    Each section's `value` is the Pydantic dump for that section; confidence
    defaults to 0.0 if the caller did not supply one (model should set it).
    """
    confidence = confidence or {}
    dumped = profile.model_dump(mode="json")
    return {
        section: {
            "value": dumped.get(section),
            "confidence": float(confidence.get(section, 0.0)),
            "rationale": "",
        }
        for section in VALID_SECTIONS
    }
