"""Raport kompetencji i lista opiekunów (0785) — DDL w ``services/competence_report_ddl.py``."""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CompetenceReport(Base):
    __tablename__ = "competence_reports"
    __table_args__ = (
        Index(
            "uq_competence_reports_token",
            "token_hash",
            unique=True,
            postgresql_where=text("token_hash IS NOT NULL"),
        ),
        Index("ix_competence_reports_queue", "status", "send_due_at"),
        Index("ix_competence_reports_candidate", "candidate_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    submission_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("application_submissions.id", ondelete="SET NULL")
    )
    # Adres ze zgłoszenia — raport idzie tam, skąd przyszła prośba.
    email: Mapped[str] = mapped_column(String(254), nullable=False)
    # waiting_cv / ready / sent / skipped / opted_out / failed (CHECK w DDL).
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="waiting_cv", server_default="waiting_cv"
    )
    # ``ReportConditions`` z formularza, dosłownie.
    conditions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # ``ReportSnapshot`` — mail po 23 h pokazuje to, co rekruter widział w kolejce.
    snapshot: Mapped[Optional[dict]] = mapped_column(JSONB)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ready_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    send_due_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    sent_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # NULL = wysłany automatycznie po terminie.
    sent_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    # „Wstrzymaj” rekrutera: pętla nie wysyła, dopóki ``held_at`` jest ustawione.
    held_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    held_by_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    token_hash: Mapped[Optional[str]] = mapped_column(String(64))
    token_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    opted_out_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[Optional[str]] = mapped_column(Text)


class CompetenceReportOwner(Base):
    """Rekruter z listy opiekunów raportów (ustawia admin)."""

    __tablename__ = "competence_report_owners"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_assigned_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
