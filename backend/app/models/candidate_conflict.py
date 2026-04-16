"""
Candidate-client conflict registry — hard filter for matching.

Use cases (IT staffing):
- `blacklist` — client explicitly forbids this candidate
- `current_employment` — candidate already works for client Y; don't send to Y again
- `nda` — NDA/cooling-off prevents placement at competitor
- `competitor` — client is a direct competitor of a place candidate just left

Active conflicts are enforced in the recommendation engine (Faza 2).
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Index, Integer, Text, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ConflictType(str, enum.Enum):
    blacklist = "blacklist"
    current_employment = "current_employment"
    nda = "nda"
    competitor = "competitor"


class CandidateConflict(Base, TimestampMixin):
    """Block-list entry: candidate X should not be matched with client Y."""

    __tablename__ = "candidate_conflicts"
    __table_args__ = (
        # Partial unique index: only one active conflict per (candidate, client)
        Index(
            "uq_candidate_conflict_active",
            "candidate_id",
            "client_id",
            unique=True,
            postgresql_where=text("active = true"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id"), nullable=False, index=True
    )

    type: Mapped[ConflictType] = mapped_column(
        Enum(ConflictType, name="conflicttype"), nullable=False
    )
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, index=True
    )
    expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    candidate = relationship("Candidate", back_populates="conflicts")
    client = relationship("Client")

    def __repr__(self) -> str:
        return (
            f"<CandidateConflict candidate={self.candidate_id} "
            f"client={self.client_id} type={self.type.value} active={self.active}>"
        )
