"""Indeks użycia technologii kandydata: kiedy i gdzie (z odczytu CV v7).

Tabela pochodna. Źródłem prawdy jest `candidates.cv_extracted_data.skill_timeline`,
a wiersze przebudowuje wyłącznie `profile_projection.replace_skill_usage`.
Istnieje po to, żeby zapytanie „używał Kafki po 2023" nie musiało przeglądać
JSONB wszystkich kandydatów.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin


class CandidateSkillUsage(Base, TimestampMixin):
    __tablename__ = "candidate_skill_usage"
    __table_args__ = (
        UniqueConstraint(
            "candidate_id",
            "skill_canonical",
            name="uq_candidate_skill_usage_candidate_skill",
        ),
        CheckConstraint(
            "provenance IN ('cv', 'manual')",
            name="ck_candidate_skill_usage_provenance",
        ),
        Index(
            "ix_candidate_skill_usage_skill_last_used",
            "skill_canonical",
            "last_used",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    skill_canonical: Mapped[str] = mapped_column(String(120), nullable=False)
    skill_raw: Mapped[str] = mapped_column(String(120), nullable=False)
    first_used: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_used: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    months: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    contexts: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    provenance: Mapped[str] = mapped_column(String(16), nullable=False, default="cv")
    source_ref: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
