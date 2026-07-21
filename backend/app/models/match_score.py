"""Cache of hybrid score breakdowns per (candidate, job) pair (Phase C1).

Populated by `scoring_service.get_cached_or_compute`. Invalidated (marked
`stale=True`) when candidate CV / skills or job must/nice changes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

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
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
    )
    total_score: Mapped[float] = mapped_column(Float, nullable=False)
    breakdown: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # Scoring formula version in effect when this row was computed. A row whose
    # version != scoring_service.SCORING_ALGORITHM_VERSION is treated as a cache
    # miss, so a formula/flag change (AI_SCORING_CONTRACT_V2) auto-invalidates
    # without a manual stale sweep. Existing rows backfill to 'score-v1-legacy'.
    scoring_algorithm_version: Mapped[str] = mapped_column(
        # 64 not 32: the version now folds in the embedding model name
        # (AI-P0-06), e.g. "score-v1-legacy+emb-voyage-3-large" = 34 chars.
        # At 32 the INSERT failed silently (caught by _upsert_breakdown's
        # except) → the whole match-score cache stopped persisting.
        String(64),
        server_default="score-v1-legacy",
        nullable=False,
    )
    scored_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stale: Mapped[bool] = mapped_column(Boolean, server_default="false", nullable=False)
    # P1-MATCH-02: last time this row was invalidated by a mark_stale_* call.
    # Acts as a compare-and-swap fence so a score compute that STARTED before an
    # invalidation cannot resurrect `stale=False` on write-back — the upsert
    # clears `stale` only when this is NULL or older than the compute's start.
    # NULL = never invalidated since the last fresh compute.
    invalidated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
