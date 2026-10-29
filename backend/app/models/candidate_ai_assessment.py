"""Ocena „Oceń z AI” jednej osoby w rekrutacji (migracja 0619).

Serwis: ``app/services/candidate_ai_assessment.py``. DDL:
``app/services/candidate_ai_assessment_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class CandidateAiAssessment(Base):
    __tablename__ = "candidate_ai_assessments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Jedno kliknięcie „Oceń z AI” (uuid z przeglądarki; paczki po kilka osób).
    batch_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    assessed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # Miejsce osoby w zaznaczeniu — remis w kolejności dzwonienia.
    selection_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # call | maybe | no_fit; NULL = „AI nie oceniło”.
    verdict: Mapped[Optional[str]] = mapped_column(String(16))
    strength: Mapped[Optional[int]] = mapped_column(SmallInteger)
    must_found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    must_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # [{"text", "quote", "source": "cv"|"note"|"profile"}] — cytaty sprawdzone.
    reasons: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    model: Mapped[Optional[str]] = mapped_column(String(64))
    error: Mapped[Optional[str]] = mapped_column(String(120))
    model_called: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    reused_from_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_ai_assessments.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
