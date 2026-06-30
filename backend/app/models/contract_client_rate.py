"""Effective-dated client-rate schedule for a contract.

A contract's client rate ("stawka klienta") can change over time — typically a
new purchase order (zamówienie) starts at a higher rate while the running order
keeps the old one. Each row is a step in the schedule: a ``rate`` that takes
effect on ``effective_from``. The contract's *current* client rate is derived at
read time — the entry with the latest ``effective_from <= today`` (see
``Contract.effective_client_rate``). This mirrors the candidate-rate schedule
(``ContractCandidateRate``) so a future-dated ``rate_change`` amendment does not
change today's rate until it takes effect — no background job needed.

Fed by ``rate_change`` amendments (each appends a step at its ``effective_date``).
The first amendment seeds a baseline step from the contract's current rate so the
history stays complete for contracts created before this feature.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractClientRate(Base, TimestampMixin):
    """One step in a contract's client-rate schedule."""

    __tablename__ = "contract_client_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Client rate in the contract's `rate_unit` / `currency`.
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 3), nullable=False)
    # Date from which this rate applies ("Obowiązuje od").
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    contract = relationship("Contract", back_populates="client_rate_schedule")

    def __repr__(self) -> str:
        return (
            f"<ContractClientRate contract={self.contract_id} "
            f"rate={self.rate} from={self.effective_from}>"
        )
