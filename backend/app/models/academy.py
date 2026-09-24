"""Akademia — szybki nabór do programów szkoleniowych (0369).

Osobny przepływ od rekrutacji pod klienta (decyzje Artura 23–24.09.2026):
ogłoszenia → sortowanie Luny → telefon z zapisem na termin w biurze →
spotkanie → zadanie → umowa → start z edycją 1. dnia miesiąca.

Stan osoby trzyma ``academy_applications`` (nie ``candidate_stages``):
tablica rekrutacji pod klienta ma bramki (DL przy „CV wysłane”, debrief
przy „Rozmowie u klienta”, blokada 12 h), których ten przepływ nie ma,
a nocny import Traffita nadpisywałby etapy ogłoszeń-źródeł.

Jedna osoba = jeden wiersz w programie (UNIQUE), więc odrzucenie jest
pamięcią na zawsze — kolejna aplikacja tylko stempluje ``reapplied_at``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

ACADEMY_STATUSES = (
    "new",
    "to_call",
    "scheduled",
    "task_given",
    "task_passed",
    "contract_sent",
    "signed",
    "rejected",
    "withdrew",
)
ACADEMY_ACTIVE_STATUSES = (
    "new",
    "to_call",
    "scheduled",
    "task_given",
    "task_passed",
    "contract_sent",
)
ACADEMY_VERDICTS = ("call", "review", "skip")


class AcademyProgram(Base):
    __tablename__ = "academy_programs"
    __table_args__ = (
        CheckConstraint(
            "max_experience_years BETWEEN 0 AND 40",
            name="ck_academy_programs_experience",
        ),
        CheckConstraint(
            "session_capacity BETWEEN 1 AND 200", name="ck_academy_programs_capacity"
        ),
        CheckConstraint(
            "task_due_days BETWEEN 1 AND 60", name="ck_academy_programs_task_days"
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    max_experience_years: Mapped[int] = mapped_column(
        Integer, nullable=False, default=6, server_default="6"
    )
    require_polish: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    luna_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    # Pytania na telefon („Umowa zlecenie — pasuje?"), lista napisów.
    conditions: Mapped[list] = mapped_column(
        JSONB, nullable=False, default=list, server_default="[]"
    )
    session_capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    task_due_days: Mapped[int] = mapped_column(
        Integer, nullable=False, default=5, server_default="5"
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class AcademyProgramSource(Base):
    __tablename__ = "academy_program_sources"

    program_id: Mapped[int] = mapped_column(
        ForeignKey("academy_programs.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    # Zgłoszenia starsze niż ta data nie wpadają (historia ogłoszenia sprzed
    # naboru). Puste = cała historia.
    since: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    added_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AcademySession(Base):
    __tablename__ = "academy_sessions"
    __table_args__ = (
        CheckConstraint(
            "capacity BETWEEN 1 AND 200", name="ck_academy_sessions_capacity"
        ),
        Index("ix_academy_sessions_program_starts", "program_id", "starts_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("academy_programs.id", ondelete="CASCADE"), nullable=False
    )
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    location: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    capacity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=8, server_default="8"
    )
    cancelled_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AcademyApplication(Base):
    __tablename__ = "academy_applications"
    __table_args__ = (
        UniqueConstraint(
            "program_id",
            "candidate_id",
            name="uq_academy_applications_program_candidate",
        ),
        CheckConstraint(
            "status IN ('new', 'to_call', 'scheduled', 'task_given', 'task_passed', "
            "'contract_sent', 'signed', 'rejected', 'withdrew')",
            name="ck_academy_applications_status",
        ),
        CheckConstraint(
            "screening_verdict IS NULL OR screening_verdict IN ('call', 'review', 'skip')",
            name="ck_academy_applications_verdict",
        ),
        CheckConstraint(
            "task_result IS NULL OR task_result IN ('passed', 'failed')",
            name="ck_academy_applications_task_result",
        ),
        CheckConstraint(
            "status <> 'rejected' OR closed_reason IS NOT NULL",
            name="ck_academy_applications_rejected_reason",
        ),
        Index("ix_academy_applications_program_status", "program_id", "status"),
        Index("ix_academy_applications_candidate", "candidate_id"),
        Index("ix_academy_applications_session", "session_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    program_id: Mapped[int] = mapped_column(
        ForeignKey("academy_programs.id", ondelete="CASCADE"), nullable=False
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    source_job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL"), nullable=True
    )
    applied_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="new", server_default="new"
    )
    screening_verdict: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    screening: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    screened_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    experience_years: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(4, 1), nullable=True
    )
    call_attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_call_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    session_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("academy_sessions.id", ondelete="SET NULL"), nullable=True
    )
    attended: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)
    task_due: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    task_result: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    contract_sent_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    signed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cohort_month: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    closed_stage: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    closed_reason: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reapplied_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(2000), nullable=True)
    updated_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
