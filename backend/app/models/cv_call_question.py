"""Pytania pod CV w ściądze do rozmowy (0650).

Jeden wiersz na parę osoba i rekrutacja, nie na wiersz etapu: każdy ruch karty
zakłada nowy wiersz ``candidate_stages``, a pytania liczą się z CV i Championa.
To pamięć podręczna wyniku modelu, którą da się odtworzyć, dlatego usunięcie
osoby albo rekrutacji kasuje ją razem z nimi.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvCallQuestions(Base):
    __tablename__ = "cv_call_questions"
    __table_args__ = (
        CheckConstraint(
            "status IN ('ready', 'failed')", name="ck_cv_call_questions_status"
        ),
        Index("ix_cv_call_questions_job", "job_id"),
    )

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(10), nullable=False, default="ready", server_default="ready"
    )
    inputs_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(80))
    questions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
