"""
Candidate rate history — track how much a candidate was paid on previous engagements.

Critical for IT staffing: lets recruiters see "what rate did this person have with
which client on what contract type" before making a new offer.
"""

import enum
from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractType(str, enum.Enum):
    b2b = "b2b"
    uop = "uop"
    zlecenie = "zlecenie"


class RateHistory(Base, TimestampMixin):
    """Candidate's historical rates, optionally tied to a client/job."""

    __tablename__ = "candidate_rate_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)

    candidate_id: Mapped[int] = mapped_column(
        ForeignKey("candidates.id"), nullable=False, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id"), nullable=True, index=True
    )
    job_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("jobs.id"), nullable=True, index=True
    )

    rate: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="PLN", nullable=False)
    contract_type: Mapped[ContractType] = mapped_column(
        Enum(ContractType, name="contracttype"), nullable=False
    )

    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[Optional[date]] = mapped_column(Date, nullable=True)

    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    recorded_by: Mapped[Optional[int]] = mapped_column(ForeignKey("users.id"))

    candidate = relationship("Candidate", back_populates="rate_history")
    client = relationship("Client")
    job = relationship("Job")

    def __repr__(self) -> str:
        return (
            f"<RateHistory candidate={self.candidate_id} "
            f"client={self.client_id} rate={self.rate} {self.currency}>"
        )
