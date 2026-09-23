"""Zapamiętane podpowiedzi Luny dla przeglądu DZ (migracja 0353).

Klucz = (wiersz etapu, skrót wejścia). Skrót obejmuje teksty obu CV,
wymagania, wersję promptu i model, więc zmiana CV albo wymagań daje nowy
wiersz, a ponowne otwarcie tego samego kandydata czyta zapamiętany wynik.
Usunięcie wiersza etapu (także kaskadą przy usunięciu kandydata) zabiera
podpowiedzi — niosą cytaty z CV.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class DzReviewHint(Base):
    __tablename__ = "dz_review_hints"
    __table_args__ = (
        UniqueConstraint(
            "candidate_stage_id", "input_hash", name="uq_dz_review_hints_stage_hash"
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    candidate_stage_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("candidate_stages.id", ondelete="CASCADE"), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    model: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
