"""Effective-dated candidate-rate schedule for a contract.

A contract's candidate rate ("stawka kandydata") can change over time. Each row
is a step in the schedule: a `rate` that takes effect on `effective_from`. The
contract's *current* candidate rate is derived at read time — the entry with the
latest `effective_from <= today` (see `Contract.effective_candidate_rate`). This
keeps history without relying on a background job to flip the value.

`effective_to` ("Obowiązuje do") is the optional planned end of a step, so a
recruiter can lay out a progressive rate ("stawka progresywna") upfront — e.g.
three rates every 3/6 months, each with its own from/to window. It is advisory:
the *current* rate is still resolved purely from `effective_from` (the next
step's `effective_from` supersedes the previous rate), so a contiguous schedule
behaves exactly as before. `effective_to` is stored for display and for planning
gaps; it never silently zeroes out a rate.

Fed by three paths (unified history):
* the "Nowy kontrakt" form (initial schedule),
* the "Edycja kontraktu" form ("Dodaj stawkę progresywną" — replaces the whole
  schedule with the planned steps), and
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
    # Optional planned end of this step ("Obowiązuje do"). Advisory only — the
    # resolver derives the current rate from `effective_from`; this documents the
    # window a progressive step was planned for. See the module docstring.
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    contract = relationship("Contract", back_populates="candidate_rate_schedule")

    def __repr__(self) -> str:
        return (
            f"<ContractCandidateRate contract={self.contract_id} "
            f"rate={self.rate} from={self.effective_from} to={self.effective_to}>"
        )
