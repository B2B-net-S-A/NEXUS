"""Snapshoty wyników Liga Mistrzów (kwartalne) + Wyścigów Miesięcznych.

Zamrażane na koniec okresu — `frozen_snapshot` (JSONB) trzyma pełny
ranking z momentu zamknięcia, żeby późniejsze zmiany w pipeline nie
modyfikowały historii.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CompetitionType(str, enum.Enum):
    """Typy konkurencji — string enum (nie Postgres ENUM, żeby łatwo dodawać)."""

    quarterly_champions_dl = "quarterly_champions_dl"
    quarterly_champions_recruiter = "quarterly_champions_recruiter"
    monthly_recommendations = "monthly_recommendations"
    monthly_placements = "monthly_placements"
    hall_of_fame = "hall_of_fame"


class CompetitionWinner(Base):
    """Jedna pozycja na podium (rank 1/2/3) dla konkretnego typu+okresu."""

    __tablename__ = "competition_winners"
    __table_args__ = (
        CheckConstraint("rank IN (1, 2, 3)", name="ck_competition_rank"),
        UniqueConstraint("competition_type", "period", "rank", name="uq_competition"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    # Wartość string enum CompetitionType, trzymana jako VARCHAR dla
    # elastyczności — dodawanie nowych typów nie wymaga migracji enum.
    competition_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # 'Q2 2026' / '2026-04' / 'all_time' — zależnie od typu.
    period: Mapped[str] = mapped_column(String(20), nullable=False)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    rank: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    points: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metric_value: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prize_pln: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Pełny ranking + metadane z momentu zamknięcia okresu.
    frozen_snapshot: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user = relationship("User", foreign_keys=[user_id])

    def __repr__(self) -> str:
        return (
            f"<CompetitionWinner type={self.competition_type} "
            f"period={self.period} rank={self.rank} user={self.user_id}>"
        )
