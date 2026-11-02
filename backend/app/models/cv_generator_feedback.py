"""Powód pobrania oryginału CV po złym wyniku generatora (migracja 0629).

Zasady: ``app/services/cv_download_policy.py``. DDL:
``app/services/cv_generator_feedback_schema.py``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.database import Base


class CvGeneratorFeedback(Base):
    __tablename__ = "cv_generator_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL")
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL")
    )
    generated_document_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("cv_generated_documents.id", ondelete="SET NULL")
    )
    # ready | failed — stan generacji, po której rekruter pobrał oryginał.
    generation_status: Mapped[str] = mapped_column(String(16), nullable=False)
    client_rule_version: Mapped[Optional[int]] = mapped_column(Integer)
    content_mode: Mapped[Optional[str]] = mapped_column(String(32))
    reasons: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    detail: Mapped[Optional[str]] = mapped_column(Text)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
