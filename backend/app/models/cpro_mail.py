"""Dziennik zdarzeń z maili CPro (0632, ``services/cpro_mail.py``)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class CproMailEvent(Base):
    __tablename__ = "cpro_mail_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # `internetMessageId`: ten sam mail w dwóch skrzynkach to jedno zdarzenie.
    message_key: Mapped[str] = mapped_column(String(998), unique=True, nullable=False)
    email_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("emails.id", ondelete="SET NULL")
    )
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    request_number: Mapped[Optional[str]] = mapped_column(String(16))
    person: Mapped[Optional[str]] = mapped_column(String(255))
    reason: Mapped[Optional[str]] = mapped_column(String(300))
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id", ondelete="SET NULL")
    )
    candidate_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("candidates.id", ondelete="SET NULL")
    )
    # done | already | notified | manual
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    outcome_text: Mapped[str] = mapped_column(String(300), nullable=False)
    notified: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
