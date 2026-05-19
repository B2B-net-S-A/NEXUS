"""Candidate Pin — short-list of candidates a user is actively considering.

See migracja 0118_candidate_pins for schema. Replaces Traffit's auto-recent
"Otwarte karty" sidebar with an intentional pin gesture from the candidate
drawer. Pinned candidates surface in a chip bar above the list and can be
multi-selected for the existing Compare flow.

Lifecycle:
- Created when the user clicks the pin icon in `CandidateDetailV2` drawer.
- Removed by clicking pin again (toggle) or via `DELETE /api/candidates/{id}/pin`.
- Cascade-deleted when either the user or the candidate is removed
  (FK ondelete=CASCADE in the migration).

This is a per-user list (not shared) — pins reflect personal short-listing
intent, not a team-wide signal. For team-wide "interesting" markers see
`talent_pools` (pool memberships) instead.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, Integer, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.user import User


class CandidatePin(Base):
    """A single (user, candidate) pin record.

    The UNIQUE(user_id, candidate_id) constraint enforces "at most one pin
    per user per candidate" — the API treats the endpoint as idempotent so
    re-POSTing returns the existing pin rather than 409. Toggle semantics
    live in the API layer, not the model.
    """

    __tablename__ = "candidate_pins"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "candidate_id", name="uq_candidate_pins_user_candidate"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    pinned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate: Mapped["Candidate"] = relationship("Candidate")
    user: Mapped["User"] = relationship("User")
