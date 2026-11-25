"""Moduł „Przegrane” w Insights (0783) — ``services/lost_review.py``.

DDL: ``services/lost_review_schema.py`` (to samo źródło czyta ``entrypoint.sh``).
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobLossReview(Base):
    """„Co zdecydowało?” przegranej rekrutacji — wiersz należy do jednego zamknięcia."""

    __tablename__ = "job_loss_reviews"
    __table_args__ = (
        CheckConstraint(
            "source IN ('client', 'ours', 'unknown')",
            name="ck_job_loss_reviews_source",
        ),
    )

    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    closed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    why: Mapped[list[str]] = mapped_column(
        ARRAY(String(32)), nullable=False, server_default=text("'{}'")
    )
    source: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    updated_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ask_reminded_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class LostReviewLesson(Base):
    """„Co zmieniamy?” ze spotkania z DL. ``scope='client'`` = zasada klienta."""

    __tablename__ = "lost_review_lessons"
    __table_args__ = (
        CheckConstraint(
            "scope IN ('job', 'client', 'all')", name="ck_lost_review_lessons_scope"
        ),
        Index("ix_lost_review_lessons_client", "client_id", text("created_at DESC")),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("clients.id", ondelete="CASCADE"), nullable=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    text: Mapped[str] = mapped_column(String(300), nullable=False)
    created_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    archived_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
