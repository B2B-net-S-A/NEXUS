"""Saved-search alerts — per-(search, candidate) dedup log.

Append-only. One ``(saved_search_id, candidate_id)`` pair = one row forever.
Used by ``app/tasks/saved_search_alerts.py``:

- **Seed**: when the bell is enabled, every candidate currently matching the
  search is logged. So an existing matcher never triggers a "new match" alert
  later just because its row got touched — only genuine transitions INTO the
  match set (a brand-new candidate, or an existing one that did not match at
  seed time) surface, since only those are absent from the log.
- **Scan**: each candidate whose ``updated_at`` advanced since the last scan
  and matches the search is checked against this log. Absent → alert + insert.
  Present → skip. INSERT is ``ON CONFLICT DO NOTHING`` so concurrent scans /
  re-runs never double-alert.

This is the primary anti-noise mechanism: a mass background update (LinkedIn
sync, experience backfill) that touches thousands of already-matching rows
generates zero alerts, because every one of them is already in the log.

Mirrors the ``marketplace_alert_log`` pattern (alert-once dedup).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class SavedSearchAlertLog(Base):
    """Append-only log dedupujący alerty zapisanych wyszukiwań per kandydat."""

    __tablename__ = "saved_search_alert_log"
    __table_args__ = (
        UniqueConstraint(
            "saved_search_id", "candidate_id", name="uq_saved_search_alert_pair"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    saved_search_id: Mapped[int] = mapped_column(
        ForeignKey("saved_searches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # NULL = seeded baseline (candidate already matched when the bell was
    # turned on, so it was never alerted). Non-NULL = the candidate was
    # actually surfaced as a new match and notified at this time.
    notified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    saved_search = relationship("SavedSearch", foreign_keys=[saved_search_id])
    candidate = relationship("Candidate", foreign_keys=[candidate_id])

    def __repr__(self) -> str:
        return (
            f"<SavedSearchAlertLog search={self.saved_search_id} "
            f"candidate={self.candidate_id}>"
        )
