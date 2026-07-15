"""Effective-dated framework-rate schedule for a contract.

A contract's framework rate ("stawka z umowy ramowej" / MSA rate) can change over
time — a client may raise the master-agreement rate mid-cooperation. Each row is a
step in the schedule: a ``rate`` that takes effect on ``effective_from``. The
contract's *current* framework rate is derived at read time — the entry with the
latest ``effective_from <= today`` (see ``Contract.effective_framework_rate``).
This mirrors the candidate-rate schedule (``ContractCandidateRate``) so a
future-dated framework-rate change does not take effect until its date — no
background job needed.

``effective_to`` ("Obowiązuje do") is the optional planned end of a step, so a
user can lay out the framework-rate progression upfront (each step with its own
from/to window). It is advisory: the *current* rate is still resolved purely from
``effective_from`` (the next step's ``effective_from`` supersedes the previous
rate). It never silently zeroes out a rate.

Unlike the candidate/client schedules the framework rate does NOT feed the margin
(it is a reference/ceiling value), so this schedule is purely informational — it
keeps the ``contracts.framework_rate`` column in sync with the step in effect
today. ``rate`` is ``NUMERIC(12, 2)`` to match ``contracts.framework_rate``
(framework rates carry grosze, e.g. 215,60 — migration 0157).

Fed by the "Nowy kontrakt" and "Edycja kontraktu" forms (each replaces the whole
schedule with the planned steps). Existing contracts have no rows; the legacy
``Contract.framework_rate`` column stays as the fallback — backward-compatible,
zero backfill.
"""

from datetime import date
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, ForeignKey, Integer, Numeric, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import TimestampMixin


class ContractFrameworkRate(Base, TimestampMixin):
    """One step in a contract's framework-rate schedule."""

    __tablename__ = "contract_framework_rates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, index=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Framework rate in the contract's `rate_unit` / `currency`. NUMERIC(12,2) to
    # match the legacy `contracts.framework_rate` column (grosze, e.g. 215,60).
    rate: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    # Date from which this rate applies ("Obowiązuje od").
    effective_from: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Optional planned end of this step ("Obowiązuje do"). Advisory only — the
    # resolver derives the current rate from `effective_from`. See the docstring.
    effective_to: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    contract = relationship("Contract", back_populates="framework_rate_schedule")

    def __repr__(self) -> str:
        return (
            f"<ContractFrameworkRate contract={self.contract_id} "
            f"rate={self.rate} from={self.effective_from} to={self.effective_to}>"
        )
