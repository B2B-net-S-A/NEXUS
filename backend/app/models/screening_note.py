import enum
from typing import Optional
from datetime import datetime

from sqlalchemy import Boolean, Enum, ForeignKey, Integer, String, Text, DateTime, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class ScreeningType(str, enum.Enum):
    initial_screening = "initial_screening"
    prep_call = "prep_call"
    follow_up = "follow_up"


class MotivationType(str, enum.Enum):
    money = "money"
    growth = "growth"
    project = "project"
    team = "team"
    work_mode = "work_mode"
    stability = "stability"
    technology = "technology"
    location = "location"


class CounterOfferRisk(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class ScreeningNote(Base):
    """Ustrukturyzowana notatka ze screeningu kandydata."""

    __tablename__ = "screening_notes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)

    screening_type: Mapped[ScreeningType] = mapped_column(
        Enum(ScreeningType), nullable=False, default=ScreeningType.initial_screening
    )

    # Motywacja
    motivation_primary: Mapped[Optional[MotivationType]] = mapped_column(
        Enum(MotivationType)
    )
    motivation_secondary: Mapped[Optional[MotivationType]] = mapped_column(
        Enum(MotivationType)
    )

    # Wynagrodzenie
    salary_expectation: Mapped[Optional[int]] = mapped_column(Integer)
    salary_currency: Mapped[Optional[str]] = mapped_column(String(10), default="PLN")
    salary_negotiable: Mapped[bool] = mapped_column(Boolean, default=False)

    # Umiejętności (JSONB: [{skill, level, notes}])
    verified_skills: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    # Oceny jakościowe
    red_flags: Mapped[Optional[str]] = mapped_column(Text)
    personality_notes: Mapped[Optional[str]] = mapped_column(Text)

    readiness_to_change: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5
    counteroffer_risk: Mapped[Optional[CounterOfferRisk]] = mapped_column(
        Enum(CounterOfferRisk)
    )

    closing_strategy: Mapped[Optional[str]] = mapped_column(Text)
    overall_impression: Mapped[Optional[int]] = mapped_column(Integer)  # 1-5

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    candidate = relationship("Candidate", backref="screening_notes")
    job = relationship("Job", backref="screening_notes")
    author = relationship("User", foreign_keys=[author_id])
    mentions = relationship(
        "ScreeningNoteMention",
        back_populates="screening_note",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<ScreeningNote id={self.id} candidate_id={self.candidate_id} type={self.screening_type}>"
