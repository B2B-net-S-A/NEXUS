"""Championi rekrutacji — osoby, które klient chce (decyzje Artura D1–D9, 15.10.2026).

Delivery Lead zaznacza jednego albo kilku kandydatów z tej rekrutacji na
liście „Championi” pod plakietką statusu w nagłówku. ``jobs.champion_found_at``
zostaje i dalej znaczy „nie szukamy” — liczy ją ``services/job_champions``
z tej tabeli (championi ∪ zatrudnieni ≥ liczba miejsc).

Żywy wiersz (``cleared_at IS NULL``) jest jeden na parę (rekrutacja,
kandydat). Zdjęcie zostawia wiersz z powodem: ``manual`` (lista w nagłówku),
``card_closed`` (karta championa zamknięta — odrzucenie, rezygnacja) albo
``removed_from_job`` (osoba usunięta z rekrutacji albo z bazy).
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
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base

CLEAR_REASONS = ("manual", "card_closed", "removed_from_job")


class JobChampion(Base):
    __tablename__ = "job_champions"
    __table_args__ = (
        CheckConstraint(
            "cleared_reason IS NULL OR cleared_reason IN "
            "('manual', 'card_closed', 'removed_from_job')",
            name="ck_job_champions_cleared_reason",
        ),
        CheckConstraint(
            "(cleared_at IS NULL) = (cleared_reason IS NULL)",
            name="ck_job_champions_cleared",
        ),
        Index(
            "ux_job_champions_live",
            "job_id",
            "candidate_id",
            unique=True,
            postgresql_where=text("cleared_at IS NULL"),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), nullable=False, index=True
    )
    marked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    marked_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    cleared_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cleared_reason: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    cleared_by_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
