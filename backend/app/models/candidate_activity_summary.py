"""Scoped cache for the candidate activity-summary AI note.

Rows are isolated by caller visibility scope and content-policy version.  The
nullable summary/generated fields also let a row act as a short generation
lease; only a compare-and-swap holder may publish the resulting prose.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateActivitySummary(Base, TimestampMixin):
    __tablename__ = "candidate_activity_summaries"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "visibility_scope_hash",
            "content_policy_version",
            name="uq_candidate_activity_summary_scope_policy",
        ),
        CheckConstraint(
            """
            (
                generation_lease_token IS NULL
                AND generation_lease_expires_at IS NULL
            )
            OR (
                generation_lease_token IS NOT NULL
                AND generation_lease_expires_at IS NOT NULL
            )
            """,
            name="ck_candidate_activity_summary_lease_pair",
        ),
        Index(
            "ix_candidate_activity_summaries_lease_expires_at",
            "generation_lease_expires_at",
            postgresql_where=text("generation_lease_expires_at IS NOT NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # NULL only while a generation lease is active (or on a failed legacy
    # placeholder). GET always filters these rows out.
    summary: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Which model produced the note (audit / cost attribution).
    model: Mapped[Optional[str]] = mapped_column(String(64))
    # Fingerprint of the gathered history that produced this note. A matching
    # hash on refresh means nothing changed → serve the cached note for free.
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # Explicit public name for freshness. ``input_hash`` stays during rollout
    # for compatibility with the original 0204 schema.
    source_version: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    visibility_scope_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, default="legacy-unscoped"
    )
    content_policy_version: Mapped[str] = mapped_column(
        String(64), nullable=False, default="legacy-unscoped"
    )
    source_manifest: Mapped[dict] = mapped_column(
        JSONB, nullable=False, default=dict, server_default="{}"
    )

    generated_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    generated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    generation_lease_token: Mapped[Optional[str]] = mapped_column(
        String(36), nullable=True
    )
    generation_lease_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover - debug helper
        return f"<CandidateActivitySummary candidate={self.candidate_id}>"
