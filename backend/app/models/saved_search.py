"""Saved searches — per-user named filter presets (Phase 4)."""

from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String
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
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    total_score: Mapped[int] = mapped_column(Integer, nullable=False)
    breakdown: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    triggered_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))
