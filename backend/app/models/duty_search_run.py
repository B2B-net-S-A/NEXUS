"""„Kto już to robił” — przebieg wyszukiwania po celu i oceny osób (0676).

DDL: ``app/services/duty_search_schema.py`` (jedno źródło dla migracji i entrypointu).
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class DutySearchRun(Base, TimestampMixin):
    __tablename__ = "duty_search_runs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
    job_id: Mapped[int | None] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    goal_title: Mapped[str | None] = mapped_column(String(300))
    goal_text: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="queued")
    plan: Mapped[dict | None] = mapped_column(JSONB)
    metrics: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    error_code: Mapped[str | None] = mapped_column(String(60))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class DutySearchResult(Base):
    __tablename__ = "duty_search_results"

    run_id: Mapped[str] = mapped_column(
        ForeignKey("duty_search_runs.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    tier: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[int | None] = mapped_column(SmallInteger)
    fit_score: Mapped[float | None] = mapped_column(Float)
    from_goal_only: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    assessment: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    feedback: Mapped[str | None] = mapped_column(String(8))
    feedback_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    feedback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
