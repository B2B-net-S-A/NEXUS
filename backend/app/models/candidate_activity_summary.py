"""AI-generated activity summary per candidate ("Podsumowanie aktywności").

One short Polish note per candidate condensing the whole activity history:
submissions to projects (position, client, last send date, interview outcome +
feedback), preferences/constraints, prior collaboration with clients, agreed
and submitted rates (range if they varied), availability / notice period and
rejection reasons — so a recruiter grasps the candidate in seconds without
reading every note.

Same caching idea as ``candidate_match_justifications``: the LLM prose is a
paid Claude call, so we keep one row per candidate and fingerprint the inputs
(``input_hash``). The "Aktualizuj notatkę" button re-gathers the history and
only pays for a new generation when something actually changed.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateActivitySummary(Base, TimestampMixin):
    __tablename__ = "candidate_activity_summaries"
    __table_args__ = (
        UniqueConstraint("candidate_id", name="uq_candidate_activity_summary"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # The note itself — short Polish prose (plain text, no markdown).
    summary: Mapped[str] = mapped_column(Text, nullable=False)

    # Which model produced the note (audit / cost attribution).
    model: Mapped[Optional[str]] = mapped_column(String(64))
    # Fingerprint of the gathered history that produced this note. A matching
    # hash on refresh means nothing changed → serve the cached note for free.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    generated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CandidateActivitySummary candidate={self.candidate_id}>"
