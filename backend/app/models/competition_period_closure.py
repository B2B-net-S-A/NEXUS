"""Zamknięcie okresu konkursu płatnego (migracja 0344).

`competition_winners` trzyma wyłącznie wiersze podium, więc „okres rozliczony,
nikt się nie zakwalifikował" i „okres z remisem czekającym na decyzję" były
nieodróżnialne od „okres jeszcze nie rozliczony". Autofreeze liczył wtedy taki
okres od nowa co godzinę przez cały następny okres — i mógł wyłonić zwycięzcę
z danych dosypanych po terminie. Wiersz tutaj jest ZAMKNIĘCIEM okresu,
niezależnie od tego, ile wierszy podium powstało.

Statusy:

* ``frozen`` — podium zapisane bez remisu na płatnym miejscu;
* ``no_winner`` — nikt nie spełnił warunków nagrody;
* ``tie_pending`` — remis na płatnym miejscu czeka na decyzję admina; miejsca
  objęte remisem NIE mają wierszy w `competition_winners` (nagroda 0 zł do
  rozstrzygnięcia), a remisujący i ich wyniki są w ``details``;
* ``tie_resolved`` — admin ustalił kolejność, wiersze podium dopisane.
"""

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
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

CLOSURE_FROZEN = "frozen"
CLOSURE_NO_WINNER = "no_winner"
CLOSURE_TIE_PENDING = "tie_pending"
CLOSURE_TIE_RESOLVED = "tie_resolved"
CLOSURE_STATUSES = (
    CLOSURE_FROZEN,
    CLOSURE_NO_WINNER,
    CLOSURE_TIE_PENDING,
    CLOSURE_TIE_RESOLVED,
)


class CompetitionPeriodClosure(Base):
    __tablename__ = "competition_period_closures"
    __table_args__ = (
        UniqueConstraint(
            "competition_type", "period", name="uq_competition_period_closures"
        ),
        CheckConstraint(
            "status IN ('frozen', 'no_winner', 'tie_pending', 'tie_resolved')",
            name="ck_competition_period_closures_status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    competition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    resolved_by: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
