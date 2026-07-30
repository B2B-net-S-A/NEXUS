"""Saved searches — per-user named filter presets (Phase 4)."""

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class SavedSearch(Base, TimestampMixin):
    """
    Named filter preset stored per user. `entity` is 'candidates' | 'jobs' | etc.
    `filters` is a free-form JSONB payload that the frontend replays into its
    current filter state.
    """

    __tablename__ = "saved_searches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    entity: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    filters: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    shared: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(255))
    # Nullable FK — when set, the search is "pinned" to a specific job and
    # the manual-search tab in the job profile surfaces it alongside the
    # user's global presets. ``ON DELETE SET NULL`` on the DB side keeps the
    # search alive after the job is archived (migration 0084).
    pinned_to_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # Saved-search alerts (migration 0129). When ``notify_new_matches`` is on,
    # the background scanner (app/tasks/saved_search_alerts.py) re-executes the
    # search and notifies the OWNER about candidates with
    # ``id > last_seen_candidate_id`` (PK watermark — cheap and race-safe).
    # The replay needs ``filters["api"]`` (GET /api/candidates params computed
    # by the FE via filtersToApiParams at save/toggle time) next to the classic
    # ``filters["qs"]`` querystring. ``unseen_count`` is a badge counter bumped
    # by the scanner; POST /saved-searches/{id}/viewed resets it and rolls
    # ``last_viewed_at`` forward — the FE highlights rows created after the
    # PREVIOUS ``last_viewed_at`` as "Nowy".
    notify_new_matches: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    # Set when retired candidate monthly-rate criteria were removed. Alerts
    # stay disabled until the owner explicitly confirms the rewritten search.
    requires_reapproval: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    last_seen_candidate_id: Mapped[Optional[int]] = mapped_column(
        Integer, nullable=True
    )
    # Watermark for the V2 scanner (migration 0131): only candidates whose
    # ``updated_at`` advanced past this are re-checked, so we catch EXISTING
    # candidates that newly match (updated CV / skill / status), not just
    # brand-new rows. NULL = alert never ran its baseline yet → first scan
    # seeds the dedup log and sets this without alerting. Dedup is enforced by
    # ``saved_search_alert_log`` (alert-once per candidate per search).
    last_scanned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    unseen_count: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, server_default="0"
    )
    last_viewed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    user = relationship("User")


class MatchHistory(Base, TimestampMixin):
    """
    Audit row per (job, candidate) match calculation — lets the UI show a
    "last matched X days ago, score Y" next to any candidate.
    """

    __tablename__ = "match_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
