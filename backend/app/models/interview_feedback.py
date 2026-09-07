"""InterviewFeedback — strukturalny feedback po interview.

Dwa warianty per CalendarEvent (UNIQUE (event_id, source)):
- candidate_side — recruiter zebrał feedback od kandydata po rozmowie
- client_side    — recruiter/DL zebrał feedback od klienta po rozmowie
"""

from __future__ import annotations

import enum
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Enum,
    ForeignKey,
    Integer,
    SmallInteger,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class FeedbackSource(str, enum.Enum):
    candidate_side = "candidate_side"
    client_side = "client_side"


class InterestLevel(str, enum.Enum):
    hot = "hot"
    warm = "warm"
    cold = "cold"
    dead = "dead"


class NextStepPreference(str, enum.Enum):
    ready_for_next = "ready_for_next"
    need_info = "need_info"
    pass_ = "pass"  # 'pass' jest keywordem — suffix _ po stronie Pythona

    @classmethod
    def _missing_(cls, value):
        # Pozwala na roundtrip między 'pass' z DB a enum.pass_
        if value == "pass":
            return cls.pass_
        return None


class InterviewDecision(str, enum.Enum):
    advance = "advance"
    reject = "reject"
    on_hold = "on_hold"


class InterviewFeedback(Base, TimestampMixin):
    """Strukturalny feedback zebrany po interview (candidate- lub client-side)."""

    __tablename__ = "interview_feedback"
    __table_args__ = (
        UniqueConstraint(
            "calendar_event_id",
            "feedback_source",
            name="uq_interview_feedback_event_source",
        ),
        CheckConstraint(
            "overall_impression IS NULL OR (overall_impression BETWEEN 1 AND 5)",
            name="ck_interview_feedback_overall_impression_range",
        ),
        CheckConstraint(
            "technical_fit IS NULL OR (technical_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_technical_fit_range",
        ),
        CheckConstraint(
            "soft_fit IS NULL OR (soft_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_soft_fit_range",
        ),
        CheckConstraint(
            "overall_fit IS NULL OR (overall_fit BETWEEN 1 AND 5)",
            name="ck_interview_feedback_overall_fit_range",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    # Nullable od 0278: werdykt hiring managera bywa zbierany bez spotkania
    # zaplanowanego w NEXUSIE (klient umawia się z kandydatem sam). UNIQUE
    # (calendar_event_id, feedback_source) zostaje — NULL-e są w Postgresie
    # różne, więc dalej pilnuje „max jeden feedback danej strony na SPOTKANIE",
    # a wiersze bez spotkania go nie dotyczą.
    calendar_event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    author_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    feedback_source: Mapped[FeedbackSource] = mapped_column(
        Enum(FeedbackSource, name="feedbacksource", create_type=False),
        nullable=False,
    )

    # ── candidate_side (nullable when source=client_side) ──
    overall_impression: Mapped[Optional[int]] = mapped_column(SmallInteger)
    interest_level: Mapped[Optional[InterestLevel]] = mapped_column(
        Enum(InterestLevel, name="interestlevel", create_type=False)
    )
    candidate_questions: Mapped[Optional[str]] = mapped_column(Text)
    concerns: Mapped[Optional[str]] = mapped_column(Text)
    next_step_preference: Mapped[Optional[NextStepPreference]] = mapped_column(
        Enum(NextStepPreference, name="nextsteppreference", create_type=False)
    )

    # ── client_side (nullable when source=candidate_side) ──
    technical_fit: Mapped[Optional[int]] = mapped_column(SmallInteger)
    soft_fit: Mapped[Optional[int]] = mapped_column(SmallInteger)
    overall_fit: Mapped[Optional[int]] = mapped_column(SmallInteger)
    decision: Mapped[Optional[InterviewDecision]] = mapped_column(
        Enum(InterviewDecision, name="interviewdecision", create_type=False)
    )
    client_questions: Mapped[Optional[str]] = mapped_column(Text)
    feedback_summary: Mapped[Optional[str]] = mapped_column(Text)
    # Powód ze słownika szablonu (0278). To ta sama pozycja, po której
    # ``services/hiring_manager_verdicts`` rozpoznaje weto — flaga
    # ``RejectionReason.disqualifies_person``. Nie kopiujemy tu samej flagi:
    # słownik bywa poprawiany, a weto ma się liczyć z BIEŻĄCEJ definicji powodu,
    # tak jak liczy je silnik weta.
    rejection_reason_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("rejection_reasons.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Relationships
    calendar_event = relationship("CalendarEvent", foreign_keys=[calendar_event_id])
    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    job = relationship("Job", foreign_keys=[job_id])
    author = relationship("User", foreign_keys=[author_id])

    def __repr__(self) -> str:
        return (
            f"<InterviewFeedback id={self.id} event={self.calendar_event_id} "
            f"source={self.feedback_source.value if self.feedback_source else None}>"
        )
