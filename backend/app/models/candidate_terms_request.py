"""Prośba o warunki kandydata (0729) — DDL w ``services/candidate_terms_schema.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateTermsRequest(Base):
    __tablename__ = "candidate_terms_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    # pracuj / jjit / career / manual — skąd przyszła aplikacja.
    source: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="queued", server_default="queued"
    )
    # link / thanks — co poszło (ustala wysyłka, nie zgłoszenie).
    action: Mapped[Optional[str]] = mapped_column(String(16))
    skip_reason: Mapped[Optional[str]] = mapped_column(String(40))
    missing: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default=text("'[]'::jsonb")
    )
    token_sha256: Mapped[Optional[str]] = mapped_column(String(64))
    recruiter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    queued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    answered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    answer_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    answers: Mapped[Optional[dict]] = mapped_column(JSONB)
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
