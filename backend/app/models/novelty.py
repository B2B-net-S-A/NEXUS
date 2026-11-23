"""Postęp osoby przy nowości NEXUSA (0625) i w lekcji nowości (0760) —
patrz ``app/data/novelties``."""

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services.novelty_schema import COMPLETED_VIA


class NoveltyProgress(Base):
    __tablename__ = "novelty_progress"
    __table_args__ = (
        CheckConstraint(
            "completed_via IS NULL OR completed_via IN ("
            + ", ".join(f"'{v}'" for v in COMPLETED_VIA)
            + ")",
            name="ck_novelty_progress_completed_via",
        ),
        Index("ix_novelty_progress_novelty", "novelty_id"),
    )

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    novelty_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    first_seen_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    seen_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    card_dismissed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    postponed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    completed_via: Mapped[Optional[str]] = mapped_column(String(10))
    reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reminded_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NoveltyLessonProgress(Base):
    """Postęp osoby w lekcji nowości (0760): pokaz → sam → pytanie."""

    __tablename__ = "novelty_lesson_progress"
    __table_args__ = (Index("ix_novelty_lesson_progress_lesson", "lesson_id"),)

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    lesson_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    shown_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    shown_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    solo_failed_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    solo_passed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    quiz_wrong_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    reviewed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    review_failed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NoveltyDailyState(Base):
    """Porcja osoby w danym dniu (0760): odłożenie i pominięcie przez admina."""

    __tablename__ = "novelty_daily_state"

    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    postponed_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    skipped_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
