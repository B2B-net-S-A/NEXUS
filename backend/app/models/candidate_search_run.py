"""Durable shared search runs and population snapshots, independent of UI."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    Index,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateSearchRun(Base, TimestampMixin):
    __tablename__ = "candidate_search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(ForeignKey("clients.id"), nullable=False)
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    state: Mapped[str] = mapped_column(
        String(20), nullable=False, default="queued", index=True
    )
    request_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )
    request_context: Mapped[dict] = mapped_column(JSONB, nullable=False)
    version_trace: Mapped[dict] = mapped_column(JSONB, nullable=False)
    population_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error_code: Mapped[str | None] = mapped_column(String(100))
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)


class CandidateSearchResult(Base):
    __tablename__ = "candidate_search_results"
    __table_args__ = (
        Index(
            "ix_candidate_search_results_page",
            "run_id",
            "eligible",
            "fit_score",
            "candidate_id",
        ),
    )

    run_id: Mapped[str] = mapped_column(
        ForeignKey("candidate_search_runs.id", ondelete="CASCADE"), primary_key=True
    )
    # Preserve the snapshot identity if a profile is deleted during the run.
    # Hydration/access checks use the current candidate table before display.
    candidate_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_version: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    eligible: Mapped[bool | None] = mapped_column(Boolean)
    fit_score: Mapped[float | None] = mapped_column(Float)
    measurement: Mapped[str | None] = mapped_column(String(24))
    evidence: Mapped[dict | None] = mapped_column(JSONB)
    exclusion_reasons: Mapped[list | None] = mapped_column(JSONB)
