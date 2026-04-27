"""Candidate Risk Profile — cached aggregate of dropout history.

See migracja 0066_candidate_risk for schema. Recomputed event-driven on every
stage transition by `app.services.candidate_risk.on_candidate_stage_change`,
plus a 24h TTL fallback (`stale_after`) handled by `get_or_compute`.
"""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class RiskLevel(str, enum.Enum):
    low = "low"
    medium = "medium"
    high = "high"


class CandidateOfferResponse(str, enum.Enum):
    """Kandydata reakcja na ofertę po akcepcie klienta.

    Tylko sensowna gdy CandidateStage.stage ∈ {acceptance, negotiation, onboarding}.
    'declined' przy późniejszym `withdrawn` = post-accept dropout (najgorszy sygnał).
    """

    pending = "pending"
    accepted = "accepted"
    declined = "declined"


class CandidateRiskProfile(Base):
    """Zagregowany profil ryzyka — odświeżany na każdej tranzycji + TTL 24h.

    Pola `*_count` to liczba wycofań w 24-miesięcznym oknie. `score` to ważona
    suma (early=1, interview=3, post_accept=10). `level` derived ze `score`:
        score < 3        → low
        3 ≤ score < 10   → medium
        score ≥ 10       → high
    `recent_events` trzyma snapshot ostatnich 5 dropoutów dla tooltipa w UI.
    """

    __tablename__ = "candidate_risk_profile"

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id", ondelete="CASCADE"), primary_key=True
    )
    level: Mapped[RiskLevel] = mapped_column(
        Enum(RiskLevel, name="risklevel", create_type=False),
        nullable=False,
        server_default="low",
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    early_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    interview_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    post_accept_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    recent_events: Mapped[Optional[list]] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    stale_after: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    candidate = relationship("Candidate", back_populates="risk_profile")

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<CandidateRiskProfile candidate={self.candidate_id} "
            f"level={self.level.value} score={self.score}>"
        )
