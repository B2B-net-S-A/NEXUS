"""Interview Questions Bank — centralna baza pytań rekrutacyjnych.

Modele:
- `InterviewQuestion` — centralna tabela pytań, tagowalnych po CC/skills/seniority.
  `client_id` kluczowe dla tenant isolation: pytania z `client_id != NULL` nigdy
  nie wyciekają do prep-kitów innych klientów.
- `JobQuestion` — m2m pin między pytaniem a jobem (z order_index do drag-drop).
- `InterviewQuestionRating` — audit trail thumb up/down (faza 1: bez wpływu na
  ranking, tylko zbieramy sygnał).

Fallback waterfall w serwisie `question_suggestions.py`:
1. pinned `JobQuestion` (is_pinned=true)
2. legacy `Job.champion_profile.screening_questions`
3. tier 1: jobs z tym samym primary CC, cosine >= 0.70
4. tier 2: jobs z overlapping secondary CC, cosine >= 0.55
5. tier 3: `ClientKnowledge` kategorii `interview_questions`
6. tier 4: auto-generate z `job.must_skills` + `requirements`
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class InterviewQuestionSource(str, enum.Enum):
    manual = "manual"
    auto_generated = "auto_generated"
    imported_from_champion = "imported_from_champion"


class InterviewQuestionType(str, enum.Enum):
    technical = "technical"
    behavioral = "behavioral"
    motivation = "motivation"
    experience = "experience"


class InterviewQuestionSeniority(str, enum.Enum):
    junior = "junior"
    mid = "mid"
    senior = "senior"
    lead = "lead"
    architect = "architect"


class JobQuestionAddedBySource(str, enum.Enum):
    manual = "manual"
    auto_from_similar = "auto_from_similar"
    auto_generated = "auto_generated"


class QuestionRatingValue(str, enum.Enum):
    up = "up"
    down = "down"


class InterviewQuestion(Base, TimestampMixin):
    """Centralna baza pytań rekrutacyjnych."""

    __tablename__ = "interview_questions"
    __table_args__ = (
        # Tenant isolation: pytania klient-specific dedupowane w obrębie klienta
        Index(
            "uq_iq_client_hash",
            "client_id",
            "normalized_text_hash",
            unique=True,
            postgresql_where="client_id IS NOT NULL",
        ),
        # Globalny bank pytań — dedup po hashu
        Index(
            "uq_iq_global_hash",
            "normalized_text_hash",
            unique=True,
            postgresql_where="client_id IS NULL",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    text: Mapped[str] = mapped_column(Text, nullable=False)
    ideal_answer: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    deal_breaker: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    competence_category_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    # ["python", "async", "fastapi"]
    skill_tags: Mapped[Optional[list]] = mapped_column(JSONB, default=list)

    seniority: Mapped[Optional[InterviewQuestionSeniority]] = mapped_column(
        Enum(InterviewQuestionSeniority, name="interviewquestionseniority"),
        nullable=True,
    )
    question_type: Mapped[Optional[InterviewQuestionType]] = mapped_column(
        Enum(InterviewQuestionType, name="interviewquestiontype"), nullable=True
    )

    source: Mapped[InterviewQuestionSource] = mapped_column(
        Enum(InterviewQuestionSource, name="interviewquestionsource"),
        nullable=False,
        default=InterviewQuestionSource.manual,
    )

    # Tenant isolation — pytania z client_id != NULL nigdy nie wyciekają
    # do prep-kitów innych klientów (filtr w question_suggestions.py).
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Przyszły semantic merge (faza 2): pytania semantycznie równoważne mogą
    # wskazywać na jedno canonical. Na start zawsze NULL.
    canonical_question_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="SET NULL"), nullable=True
    )

    # sha256 z text po normalizacji (lowercase + trim + collapse whitespace)
    normalized_text_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, index=True
    )

    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )
    client = relationship("Client", foreign_keys=[client_id])
    creator = relationship("User", foreign_keys=[created_by])
    canonical = relationship(
        "InterviewQuestion", remote_side=[id], foreign_keys=[canonical_question_id]
    )
    job_links = relationship(
        "JobQuestion", back_populates="question", cascade="all, delete-orphan"
    )
    ratings = relationship(
        "InterviewQuestionRating",
        back_populates="question",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return (
            f"<InterviewQuestion id={self.id} "
            f"cc={self.competence_category_id} client={self.client_id}>"
        )


class JobQuestion(Base):
    """Pin pytania do konkretnego joba (m2m)."""

    __tablename__ = "job_questions"
    __table_args__ = (
        UniqueConstraint("job_id", "question_id", name="uq_job_question"),
        Index("ix_job_questions_job_order", "job_id", "order_index"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    is_pinned: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    added_by_source: Mapped[JobQuestionAddedBySource] = mapped_column(
        Enum(JobQuestionAddedBySource, name="jobquestionaddedbysource"),
        nullable=False,
        default=JobQuestionAddedBySource.manual,
    )
    added_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Fractional indexing — drag-drop bez kolizji (między 1000.0 i 2000.0 daj 1500.0)
    order_index: Mapped[float] = mapped_column(Float, nullable=False, default=1000.0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    job = relationship("Job", foreign_keys=[job_id], back_populates="question_links")
    question = relationship(
        "InterviewQuestion", foreign_keys=[question_id], back_populates="job_links"
    )
    added_by_user = relationship("User", foreign_keys=[added_by_user_id])

    def __repr__(self) -> str:
        return (
            f"<JobQuestion job={self.job_id} question={self.question_id} "
            f"pinned={self.is_pinned} order={self.order_index}>"
        )


class InterviewQuestionRating(Base):
    """Audit trail oceny pytania po rozmowie. Faza 1: tylko zbieramy sygnał."""

    __tablename__ = "interview_question_ratings"
    __table_args__ = (Index("ix_iqr_question_created", "question_id", "created_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    question_id: Mapped[int] = mapped_column(
        ForeignKey("interview_questions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL"), nullable=True, index=True
    )

    rating: Mapped[QuestionRatingValue] = mapped_column(
        Enum(QuestionRatingValue, name="questionratingvalue"), nullable=False
    )
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    question = relationship(
        "InterviewQuestion", foreign_keys=[question_id], back_populates="ratings"
    )
    user = relationship("User", foreign_keys=[user_id])
    job = relationship("Job", foreign_keys=[job_id])
    candidate = relationship("Candidate", foreign_keys=[candidate_id])

    def __repr__(self) -> str:
        return (
            f"<InterviewQuestionRating q={self.question_id} "
            f"user={self.user_id} rating={self.rating}>"
        )
