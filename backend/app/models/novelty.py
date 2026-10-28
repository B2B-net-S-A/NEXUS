"""Postęp osoby przy nowości NEXUSA (0615) — patrz ``app/data/novelties``."""

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
