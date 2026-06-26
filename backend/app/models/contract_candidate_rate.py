"""Effective-dated candidate-rate schedule for a contract.

A contract's candidate rate ("stawka kandydata") can change over time. Each row
is a step in the schedule: a `rate` that takes effect on `effective_from`. The
contract's *current* candidate rate is derived at read time — the entry with the
latest `effective_from <= today` (see `Contract.effective_candidate_rate`). This
keeps history without relying on a background job to flip the value.

Fed by two paths (unified history):
* the "Nowy kontrakt" form (initial schedule), and
* `rate_change` amendments (each appends a step at its `effective_date`).
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractCandidateRate(Base, TimestampMixin):
    """One step in a contract's candidate-rate schedule."""

    __tablename__ = "contract_candidate_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Candidate rate in the contract's `rate_unit` / `currency`.
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    # Date from which this rate applies ("Obowiązuje od").
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    contract = relationship("Contract", back_populates="candidate_rate_schedule")

    def __repr__(self) -> str:
        return (
            f"<ContractCandidateRate contract={self.contract_id} "
            f"rate={self.rate} from={self.effective_from}>"
        )
