"""Terminy rozmowy od klienta i wybór kandydata (0338).

Przekazanie, które dziś żyje w mailach: DL dostaje od klienta kilka slotów,
przekazuje je rekruterowi, rekruter ustala termin z kandydatem i wraca do DL,
DL potwierdza klientowi. Wiersz niesie to przekazanie, a potwierdzenie zakłada
wydarzenie ``client_interview`` w kalendarzu rekrutera — od niego liczy się
„zadzwoń ≤30 min po” i debrief.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin

SLOT_STATUS_AWAITING_RECRUITER = "awaiting_recruiter"
SLOT_STATUS_AWAITING_DL = "awaiting_dl"
SLOT_STATUS_CONFIRMED = "confirmed"
SLOT_STATUS_CANCELLED = "cancelled"
OPEN_SLOT_STATUSES = (SLOT_STATUS_AWAITING_RECRUITER, SLOT_STATUS_AWAITING_DL)
SLOT_STATUSES = (*OPEN_SLOT_STATUSES, SLOT_STATUS_CONFIRMED, SLOT_STATUS_CANCELLED)


class ClientInterviewSlotRequest(Base, TimestampMixin):
    __tablename__ = "client_interview_slot_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('awaiting_recruiter', 'awaiting_dl', 'confirmed', 'cancelled')",
            name="ck_interview_slot_requests_status",
        ),
        CheckConstraint(
            "duration_minutes BETWEEN 15 AND 480",
            name="ck_interview_slot_requests_duration",
        ),
        Index("ix_interview_slot_requests_candidate_job", "candidate_id", "job_id"),
        Index("ix_interview_slot_requests_status", "status"),
        Index("ix_interview_slot_requests_recruiter", "recruiter_id"),
        # Jeden OTWARTY wniosek na parę — drugi to prawie zawsze podwójne
        # kliknięcie albo dwie osoby robiące to samo; potwierdzone i anulowane
        # zostają jako historia.
        Index(
            "uq_interview_slot_requests_open_pair",
            "candidate_id",
            "job_id",
            unique=True,
            postgresql_where=text("status IN ('awaiting_recruiter', 'awaiting_dl')"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    recruiter_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # [{"start": ISO, "end": ISO}] — kolejność = kolejność od klienta.
    slots: Mapped[list] = mapped_column(JSONB, nullable=False)
    duration_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, default=60, server_default="60"
    )
    respond_by: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(24),
        nullable=False,
        default=SLOT_STATUS_AWAITING_RECRUITER,
        server_default=SLOT_STATUS_AWAITING_RECRUITER,
    )
    chosen_index: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    chosen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    chosen_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    event_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("calendar_events.id", ondelete="SET NULL"), nullable=True
    )
