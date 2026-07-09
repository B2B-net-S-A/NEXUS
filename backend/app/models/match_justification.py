"""LLM-generated match justification per (candidate, job) pair.

Powers the "Dopasowanie" tab on the candidate detail page: an AI prose
explanation of *why* the hybrid composite score (from `scoring_service`) is what
it is — a `Podsumowanie` paragraph, a `Może być dobrym wyborem, ponieważ` bullet
list, and a `Do weryfikacji` (watch-outs) list. Modelled on Traffit's AI scoring
panel and the reserved :class:`AIFeatureKey.scoring` capability.

Why cache the prose in a table (not recompute per view):
- The deterministic score is cheap; the LLM prose is a paid Claude call. One row
  per (candidate, job) means the tab is generated once and served from cache on
  every re-open. `input_hash` fingerprints the inputs (CV + requirements +
  champion + score) so the justification auto-regenerates only when the inputs
  that produced it actually change — the same auto-invalidation idea as
  ``candidate_job_match_scores.stale``.

`rating` / `rating_comment` back the "Oceń ten scoring" thumbs-up/down feedback,
mirroring the champion-suggestion rating pattern (-1 / 0 / +1).
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateMatchJustification(Base, TimestampMixin):
    __tablename__ = "candidate_match_justifications"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "job_id", name="uq_candidate_match_justification"
        ),
        CheckConstraint(
            "rating IS NULL OR rating IN (-1, 0, 1)",
            name="chk_candidate_match_justification_rating",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # Composite score (0-100) snapshotted at generation time so the ring stays
    # consistent with the prose even if the live cache is later recomputed.
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    # "Podsumowanie" — 2-4 sentence prose verdict (Polish).
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    # "Może być dobrym wyborem, ponieważ" — evidence-backed positive bullets.
    pros: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    # "Do weryfikacji / luki" — gaps and things to confirm in screening.
    watchouts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)

    # Which model produced the prose (audit / cost attribution).
    model: Mapped[Optional[str]] = mapped_column(String(64))
    # Fingerprint of the inputs that produced this justification. A mismatch on
    # read means the CV / requirements / champion / score changed → regenerate.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # "Oceń ten scoring" feedback: -1 (kciuk w dół) / +1 (kciuk w górę) / 0 reset.
    rating: Mapped[Optional[int]] = mapped_column(SmallInteger)
    rating_comment: Mapped[Optional[str]] = mapped_column(Text)
    rated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    rated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return (
            f"<CandidateMatchJustification candidate={self.candidate_id} "
            f"job={self.job_id} score={self.score}>"
        )
