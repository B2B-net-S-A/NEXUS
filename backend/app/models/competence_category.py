"""Competence Category — biznesowa kategoria kompetencji rekruterskiej.

CC to pełnoprawny byt: każdy projekt (Job) należy do jednej CC, a rekruterzy
są przypisywani do jednej lub wielu CC (tabela `user_competence_categories`).
Kandydat może mieć wiele CC (M2M `candidate_competence_categories`), z jedną
oznaczoną jako `is_primary` — źródło oznaczeń to AI (auto/suggested) albo
manual override. Podczas tworzenia projektu system sugeruje CC (embedding +
keywords) i automatycznie dopisuje rekruterów z danej CC jako
`JobCollaborator` z `source="auto_cc"`.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CandidateCcCategorySource(str, enum.Enum):
    """Skąd pochodzi przypisanie CC do kandydata."""

    ai_auto = "ai_auto"  # embedding similarity ≥ 0.80 — auto-add
    ai_suggested = "ai_suggested"  # 0.60–0.80 — sugestia do akceptacji
    manual = "manual"  # ręczny override (recruiter/admin)


class CompetenceCategory(Base):
    """Biznesowa kategoria kompetencji (np. Rozwój Oprogramowania, Dane i AI)."""

    __tablename__ = "competence_categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    slug: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, index=True
    )
    name_pl: Mapped[str] = mapped_column(String(120), nullable=False)
    name_en: Mapped[str] = mapped_column(String(120), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    keywords: Mapped[list] = mapped_column(JSONB, default=list, nullable=False)
    embedding_id: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user_assignments = relationship(
        "UserCompetenceCategory",
        back_populates="competence_category",
        cascade="all, delete-orphan",
    )

    def __repr__(self) -> str:
        return f"<CompetenceCategory id={self.id} slug={self.slug}>"


class UserCompetenceCategory(Base):
    """Przypisanie user\u2194CC (M2M). `is_primary` = g\u0142\u00f3wna CC u\u017cytkownika."""

    __tablename__ = "user_competence_categories"
    __table_args__ = (
        UniqueConstraint("user_id", "competence_category_id", name="uq_user_cc"),
        CheckConstraint(
            "priority IS NULL OR priority IN (1, 2)", name="ck_user_cc_priority"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competence_category_id: Mapped[int] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Sourcer priority w kategorii: 1 = 1st priority, 2 = 2nd priority,
    # NULL = nieokreślony (backward-compat). Używane w macierzy
    # "Sourcerzy × Kategoria" na panelu Head of Recruitment.
    priority: Mapped[Optional[int]] = mapped_column(SmallInteger, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", foreign_keys=[user_id])
    competence_category = relationship(
        "CompetenceCategory", back_populates="user_assignments"
    )

    def __repr__(self) -> str:
        return (
            f"<UserCompetenceCategory user={self.user_id} "
            f"cc={self.competence_category_id} primary={self.is_primary}>"
        )


class CandidateCompetenceCategory(Base):
    """Przypisanie kandydat↔CC (M2M). `is_primary` = główna CC kandydata.

    Kandydat może mieć do 3 CC (1 primary + 2 secondary). Źródło oznaczenia
    (`source`) pozwala odróżnić auto-assignmenty od ręcznych override'ów —
    ręczne nigdy nie są nadpisywane przez re-klasyfikację AI.
    """

    __tablename__ = "candidate_competence_categories"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id", "competence_category_id", name="uq_candidate_cc"
        ),
        CheckConstraint(
            "confidence_score >= 0.0 AND confidence_score <= 1.0",
            name="ck_candidate_cc_confidence",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competence_category_id: Mapped[int] = mapped_column(
        ForeignKey("competence_categories.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confidence_score: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source: Mapped[CandidateCcCategorySource] = mapped_column(
        Enum(
            CandidateCcCategorySource,
            name="candidatecccategorysource",
            create_type=False,
        ),
        default=CandidateCcCategorySource.manual,
        server_default=CandidateCcCategorySource.manual.value,
        nullable=False,
    )
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    candidate = relationship("Candidate", back_populates="competence_categories")
    competence_category = relationship(
        "CompetenceCategory", foreign_keys=[competence_category_id]
    )

    def __repr__(self) -> str:
        return (
            f"<CandidateCompetenceCategory candidate={self.candidate_id} "
            f"cc={self.competence_category_id} primary={self.is_primary} "
            f"score={self.confidence_score:.2f}>"
        )
