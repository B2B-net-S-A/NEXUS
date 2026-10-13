"""Pominięta uwaga QC CV albo edytora — „To nieprawda” (migracja 0439).

Pominięcie dotyczy pary (kandydat, rekrutacja), nie jednego pliku CV: ta sama
uwaga o tej samej osobie w tej rekrutacji zostaje pominięta także po nowym
CV. Wiersz z ``restored_at`` jest historią (kto przywrócił i dlaczego); aktywne
pominięcie pary i klucza jest jedno.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CvFindingDismissal(Base):
    __tablename__ = "cv_finding_dismissals"
    __table_args__ = (
        Index(
            "uq_cv_finding_dismissals_active",
            "candidate_id",
            "job_id",
            "source",
            "finding_key",
            unique=True,
            postgresql_where=text("restored_at IS NULL"),
        ),
        Index("ix_cv_finding_dismissals_created", "created_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_stage_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("candidate_stages.id", ondelete="SET NULL"), nullable=True
    )
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    check_key: Mapped[str] = mapped_column(String(40), nullable=False)
    finding_key: Mapped[str] = mapped_column(String(400), nullable=False)
    label: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(String(32), nullable=False)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    evidence_quote: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    blocking: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("false")
    )
    dismissed_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    restored_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    restored_by_user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    restored_reason: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
