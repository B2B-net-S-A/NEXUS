"""Opieka po odejściu — para osoby z wyłączonym kontem i jej Delivery Lead (0617).

DDL w ``services/departure_care_schema.py``; reguły w
``docs/claude/rekrutacja-tablica/odejscie-rekrutera-opieka-delivery-leada.md``.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, ForeignKey, Index, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class PairDepartureCare(Base):
    __tablename__ = "pair_departure_care"
    # Nazwy jak w ``departure_care_schema.TABLE_DDL`` — jeden indeks, nie dwa.
    __table_args__ = (
        Index("ix_pair_departure_care_caretaker", "caretaker_user_id"),
        Index("ix_pair_departure_care_departed", "departed_user_id"),
        Index("ix_pair_departure_care_job", "job_id"),
    )

    candidate_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    job_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("jobs.id", ondelete="CASCADE"), primary_key=True
    )
    departed_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    caretaker_user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    # Skąd opiekun: ``job_dl`` (DL rekrutacji), ``client_dl`` (główny DL
    # klienta), ``hor`` (Head of Recruitment).
    via: Mapped[str] = mapped_column(Text, nullable=False)
    reminded_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
