"""Pydantic schemas for multi-row candidate source attribution (#4)."""

from datetime import datetime
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

from app.models.candidate_source_event import SourceChannel


class CandidateSourceEventOut(BaseModel):
    id: int
    candidate_id: int
    channel: SourceChannel
    channel_label: str
    job_id: Optional[int]
    utm_source: Optional[str]
    utm_medium: Optional[str]
    utm_campaign: Optional[str]
    utm_term: Optional[str]
    utm_content: Optional[str]
    note: Optional[str]
    captured_at: datetime
    created_at: datetime

    model_config = {"from_attributes": True}


class CandidateSourceEventCreate(BaseModel):
    """Manual creation payload (recruiter or import script).

    UTM fields are optional — populated by the public /apply landing page
    when query params are present (?utm_source=linkedin&utm_campaign=may26).
    """

    channel: SourceChannel
    job_id: Optional[int] = None
    utm_source: Optional[str] = Field(None, max_length=120)
    utm_medium: Optional[str] = Field(None, max_length=120)
    utm_campaign: Optional[str] = Field(None, max_length=120)
    utm_term: Optional[str] = Field(None, max_length=120)
    utm_content: Optional[str] = Field(None, max_length=120)
    note: Optional[str] = Field(None, max_length=500)
    captured_at: Optional[datetime] = Field(
        None,
        description=("Override timestamp for backfill imports. Defaults to NOW()."),
    )


class SourceFunnelRow(BaseModel):
    """One row of the /reports/sources aggregation."""

    channel: SourceChannel
    channel_label: str
    utm_source: Optional[str] = None
    utm_campaign: Optional[str] = None
    candidates_total: int
    hired: int = Field(0, description="How many of these reached `hired` stage")
    hire_rate_pct: float = Field(
        0.0,
        description="hired / candidates_total * 100, rounded to 1 decimal.",
    )


class SourceReportResponse(BaseModel):
    period_start: datetime
    period_end: datetime
    rows: List[SourceFunnelRow]
    # Audyt statystyk 14.09.2026 (A05): model atrybucji i pokrycie jadą przy
    # liczbach, bo sam podział na kanały nie mówi, ilu kandydatów źródła NIE ma.
    attribution_model: Literal["multi_touch"] = Field(
        "multi_touch",
        description=(
            "Kandydat liczony w każdym kanale z kontaktem w oknie — wiersze się "
            "nie sumują."
        ),
    )
    unique_candidates: int = Field(
        0, description="Unikalni kandydaci z datowanym zdarzeniem źródła w oknie."
    )
    new_candidates_total: int = Field(
        0, description="Kandydaci dodani do bazy w oknie."
    )
    new_candidates_without_source: int = Field(
        0,
        description="Z nich bez żadnego datowanego zdarzenia źródła.",
    )
    undated_source_events: int = Field(
        0,
        description=(
            "Zdarzenia źródeł z importu bez prawdziwej daty (cała baza) — "
            "pominięte w oknie."
        ),
    )
