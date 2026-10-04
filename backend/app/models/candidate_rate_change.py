"""Zmiana stawki kandydata w trakcie procesu — 0418.

Opis kolumn i słowników: ``app/services/candidate_rate_change_schema.py``.
Reguły: ``app/services/candidate_rate_change.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CandidateRateChange(Base):
    __tablename__ = "candidate_rate_changes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False
    )
    stage_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidate_stages.id", ondelete="SET NULL")
    )
    previous_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    previous_unit: Mapped[Optional[str]] = mapped_column(String(20))
    previous_currency: Mapped[Optional[str]] = mapped_column(String(3))
    previous_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    requested_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    requested_unit: Mapped[str] = mapped_column(String(20), nullable=False)
    requested_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="PLN", server_default="PLN"
    )
    requested_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    agreed_amount: Mapped[Optional[Decimal]] = mapped_column(Numeric(12, 2))
    agreed_unit: Mapped[Optional[str]] = mapped_column(String(20))
    agreed_currency: Mapped[Optional[str]] = mapped_column(String(3))
    agreed_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(
        String(20), nullable=False, default="other", server_default="other"
    )
    note: Mapped[Optional[str]] = mapped_column(Text)
    negotiable: Mapped[Optional[str]] = mapped_column(String(10))
    feedback_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("interview_feedback.id", ondelete="SET NULL")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    requires_decision: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    # Kolumna Tablicy w chwili zgłoszenia (np. „cv_sent”) — treść powiadomień
    # i raport, bez ponownego liczenia historii etapów.
    board_column: Mapped[Optional[str]] = mapped_column(String(30))
    negotiator_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    negotiation_target_hourly: Mapped[Optional[Decimal]] = mapped_column(Numeric(10, 2))
    negotiation_due: Mapped[Optional[date]] = mapped_column(Date)
    outcome: Mapped[Optional[str]] = mapped_column(String(10))
    outcome_note: Mapped[Optional[str]] = mapped_column(Text)
    outcome_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    outcome_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    decision: Mapped[Optional[str]] = mapped_column(String(20))
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    decided_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
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
