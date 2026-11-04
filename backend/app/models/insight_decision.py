"""Decyzja o sprawie z zakładki „Wnioski” (0646) — ``services/insights_wnioski.py``."""

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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class InsightDecision(Base):
    __tablename__ = "insight_decisions"
    __table_args__ = (
        CheckConstraint(
            "state IN ('approved', 'later', 'rejected')",
            name="ck_insight_decisions_state",
        ),
        Index(
            "ix_insight_decisions_key_at",
            "insight_key",
            text("decided_at DESC"),
            text("id DESC"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    insight_key: Mapped[str] = mapped_column(String(64), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    decided_by_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # Liczba z ostatnich 30 dni, od której zależy „Nie” (powrót przy dwukrotnym wzroście).
    count_at_decision: Mapped[int] = mapped_column(Integer, nullable=False)
    # Ta sama liczba tak, jak stała na ekranie: „1 na 3”, „21%”.
    number_at_decision: Mapped[str] = mapped_column(String(32), nullable=False)
    return_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    review_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
