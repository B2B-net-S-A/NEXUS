"""Targ kandydatów — dedup log.

Append-only tabela. Jedna para (candidate_id, job_id) = jeden wpis na zawsze.
Używana w `marketplace_service.scan_job_for_marketplace_matches` — INSERT jest
warunkowany przez `ON CONFLICT DO NOTHING`, więc drugi skan tego samego jobu
nigdy nie wygeneruje duplikatu notyfikacji.

Wiersz jest zapisywany ZAWSZE gdy score >= threshold, nawet jeśli notyfikacja
nie dotarła (np. recipient inactive). To celowe — reaktywacja usera nie ma
odpalić historii matchy.
"""

from datetime import datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class MarketplaceAlertLog(Base):
    """Append-only log dedupujący powiadomienia z Targu kandydatów."""

    __tablename__ = "marketplace_alert_log"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_id", name="uq_marketplace_alert_pair"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    job_id: Mapped[int] = mapped_column(
        ForeignKey("jobs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    score: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    notified_candidate_owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    notified_job_owner_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    candidate = relationship("Candidate", foreign_keys=[candidate_id])
    job = relationship("Job", foreign_keys=[job_id])

    def __repr__(self) -> str:
        return (
            f"<MarketplaceAlertLog candidate={self.candidate_id} "
            f"job={self.job_id} score={self.score}>"
        )
