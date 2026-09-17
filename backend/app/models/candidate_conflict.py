"""
Candidate-client conflict registry.

Use cases (IT staffing):
- `blacklist` — client explicitly forbids this candidate
- `current_employment` — candidate already works for client Y; don't send to Y again
- `nda` — NDA/cooling-off prevents placement at competitor
- `competitor` — client is a direct competitor of a place candidate just left

Since 17.09.2026 every type is a SOFT warning in matching/assignment (visible
with a badge, assignable) — see ``services/candidate_job_eligibility.py``.
A conflict with ``expires_at`` in the past is inactive for every reader; the
row itself stays ``active`` as history (the state is derived at read time).
"""

import enum
from datetime import datetime
from typing import Iterable, Optional, Union

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    Text,
    and_,
    or_,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ConflictType(str, enum.Enum):
    blacklist = "blacklist"
    current_employment = "current_employment"
    nda = "nda"
    competitor = "competitor"


CONFLICT_TYPE_LABELS: dict[str, str] = {
    "blacklist": "Blacklist",
    "current_employment": "Obecne zatrudnienie",
    "nda": "NDA / cooling-off",
    "competitor": "Konkurencja",
}

#: Kolejność powagi, gdy u jednego klienta kandydat ma KILKA aktywnych konfliktów
#: różnych typów (dozwolone od 0321). Jedno źródło — czytają ją polityka
#: dopuszczalności (``_CLIENT_CONFLICT_REASONS``) i
#: ``recommendation_filters.load_active_conflicts_bulk``.
CONFLICT_TYPE_PRECEDENCE: tuple[str, ...] = (
    "blacklist",
    "nda",
    "competitor",
    "current_employment",
)
_CONFLICT_RANK = {t: i for i, t in enumerate(CONFLICT_TYPE_PRECEDENCE)}


def conflict_type_rank(conflict_type: Union[str, "ConflictType"]) -> int:
    key = (
        conflict_type.value
        if isinstance(conflict_type, ConflictType)
        else str(conflict_type)
    )
    return _CONFLICT_RANK.get(key, len(CONFLICT_TYPE_PRECEDENCE))


def dominant_conflict_type(
    types: Iterable["ConflictType"],
) -> Optional["ConflictType"]:
    return min(types, key=conflict_type_rank, default=None)


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


def active_unexpired_clause(now: datetime):
    """SQL „aktywny i niewygasły" — jedna definicja dla wszystkich czytelników."""
    return and_(
        CandidateConflict.active.is_(True),
        or_(
            CandidateConflict.expires_at.is_(None),
            CandidateConflict.expires_at > now,
        ),
    )
