"""Champion Profile AI suggestions model (Phase 14 — AI Intake).

A suggestion is an AI-generated delta-patch for `jobs.champion_profile` that
a Delivery Lead can review section-by-section and apply or reject. Source can
be a pasted JD, a Fireflies transcript, a CloudTalk call, or a manual
consultant note.
"""

from __future__ import annotations

import enum
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class SuggestionSource(str, enum.Enum):
    jd_paste = "jd_paste"
    fireflies_meeting = "fireflies_meeting"
    cloudtalk_call = "cloudtalk_call"
    manual_consultant_note = "manual_consultant_note"
    # Phase 15: draft generated from top-K semantically similar CLOSED jobs
    # whose champion_profile is already populated (same-client preferred).
    historical_jobs = "historical_jobs"


class SuggestionStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"
    partially_accepted = "partially_accepted"
    superseded = "superseded"


class ChampionProfileSuggestion(Base, TimestampMixin):
    """AI-generated draft of the Champion Profile for a Job, awaiting review."""

    __tablename__ = "champion_profile_suggestions"
    __table_args__ = (
        Index("ix_champion_suggestions_job_status", "job_id", "status"),
        Index(
            "ix_champion_suggestions_job_created_at",
            "job_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )

    source_type: Mapped[SuggestionSource] = mapped_column(
        Enum(
            SuggestionSource,
            name="champion_suggestion_source",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
    )
    source_ref: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    # Delta-patch per section. Shape:
    #   { "<section>": { "value": <any>, "confidence": 0..1, "rationale": "..." } }
    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )

    status: Mapped[SuggestionStatus] = mapped_column(
        Enum(
            SuggestionStatus,
            name="champion_suggestion_status",
            native_enum=True,
            create_type=False,
        ),
        nullable=False,
        default=SuggestionStatus.pending,
    )

    created_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Phase 15 / Phase C: optional DL feedback after apply/reject.
    # -1 = bezużyteczne, 0 = nijak, 1 = trafione. NULL = brak oceny.
    # Enforced by a DB CHECK constraint (migracja 0057).
    rating: Mapped[Optional[int]] = mapped_column(nullable=True)
    rating_comment: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Relationships
    job = relationship("Job")
    created_by = relationship("User", foreign_keys=[created_by_id])
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])

    def __repr__(self) -> str:
        return (
            f"<ChampionProfileSuggestion id={self.id} job={self.job_id} "
            f"source={self.source_type.value} status={self.status.value}>"
        )
