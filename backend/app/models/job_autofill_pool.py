"""Pula dopełniania „Nowych” (0513) — DDL w ``services/job_autofill_pool_schema.py``."""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class JobAutofillPool(Base):
    __tablename__ = "job_autofill_pool"
    __table_args__ = (
        Index("ix_job_autofill_pool_job_score", "job_id", "score"),
        Index("ix_job_autofill_pool_candidate_id", "candidate_id"),
    )

    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    run_id: Mapped[str] = mapped_column(String(36), nullable=False)
    cv_revision: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    evidence: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
