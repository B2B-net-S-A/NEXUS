"""Cache of hybrid score breakdowns per (candidate, job) pair (Phase C1).

Populated by `scoring_service.get_cached_or_compute`. Invalidated (marked
`stale=True`) when candidate CV / skills or job must/nice changes.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    PrimaryKeyConstraint,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateJobMatchScore(Base):
    __tablename__ = "candidate_job_match_scores"
    __table_args__ = (
        PrimaryKeyConstraint(
            "candidate_id", "job_id", "profile_id", name="pk_candidate_job_match_scores"
        ),
    )

    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    # 0 = built-in DEFAULT_PROFILE (no row in scoring_weight_profiles);
    # >0 = id of a custom profile.
    profile_id: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    profile_version: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    scoring_algorithm_version: Mapped[str] = mapped_column(
        String(40), nullable=False, server_default="legacy"
    )
    index_version: Mapped[str] = mapped_column(
        String(255), nullable=False, server_default="legacy"
    )
    candidate_source_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="legacy"
    )
    job_source_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, server_default="legacy"
    )
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stale: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
