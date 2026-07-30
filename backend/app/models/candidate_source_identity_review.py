"""Durable identity decisions for candidate-bound notes and documents.

Sources that are confirmed to describe another person stay attached to the
candidate for human review, but are quarantined from AI and derived
projections.  The raw observed identity is deliberately not persisted here;
``evidence`` contains only booleans and one-way fingerprints.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
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
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateSourceIdentityReview(Base, TimestampMixin):
    """Latest auditable identity decision for one candidate source."""

    __tablename__ = "candidate_source_identity_reviews"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "source_kind",
            "source_id",
            name="uq_candidate_source_identity_review",
        ),
        CheckConstraint(
            "source_kind IN ('note', 'document', 'legacy_cv', 'talent_radar_cv')",
            name="ck_candidate_source_identity_review_kind",
        ),
        CheckConstraint(
            "decision IN ('confirmed_match', 'confirmed_mismatch', 'inconclusive')",
            name="ck_candidate_source_identity_review_decision",
        ),
        CheckConstraint(
            """
            (override_at IS NULL AND override_by_id IS NULL
             AND override_reason IS NULL)
            OR
            (override_at IS NOT NULL AND override_by_id IS NOT NULL
             AND override_reason IS NOT NULL
             AND length(btrim(override_reason)) >= 3)
            """,
            name="ck_candidate_source_identity_review_override",
        ),
        Index(
            "ix_candidate_source_identity_reviews_candidate",
            "candidate_id",
        ),
        Index(
            "ix_candidate_source_identity_reviews_quarantine",
            "candidate_id",
            "source_kind",
            "source_id",
            postgresql_where=text(
                "decision = 'confirmed_mismatch' AND override_at IS NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
    )
    source_kind: Mapped[str] = mapped_column(String(24), nullable=False)
    source_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    provenance: Mapped[str] = mapped_column(String(80), nullable=False)
    detector_version: Mapped[str] = mapped_column(String(64), nullable=False)
    # Never store names or source text. Values are limited by the service to
    # booleans, counters and HMAC-SHA256 fingerprints.
    evidence: Mapped[dict] = mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    reviewed_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
    )
    override_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    override_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    override_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    candidate = relationship("Candidate")
    reviewed_by = relationship("User", foreign_keys=[reviewed_by_id])
    override_by = relationship("User", foreign_keys=[override_by_id])

    @property
    def is_quarantined(self) -> bool:
        return self.decision == "confirmed_mismatch" and self.override_at is None
