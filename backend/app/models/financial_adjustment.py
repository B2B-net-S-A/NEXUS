"""Korekty finansowe — audytowalny, niemutowalny rejestr (plan PR 6).

Ręczne korekty do raportów finansowych (np. rabat, jednorazowa premia,
korekta faktury), których nie da się wyprowadzić z kontraktów. Zasady:
- immutable audit trail: wiersz po utworzeniu NIE jest edytowalny ani
  usuwalny — jedyne przejście to draft → approved (osobny endpoint),
- write: wyłącznie admin; read: admin + delivery_lead,
- kwota Decimal + waluta; do sum wchodzą TYLKO approved (po kursie
  raportowym, jak reszta finansów).
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Numeric, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AdjustmentStatus(str, enum.Enum):
    draft = "draft"
    approved = "approved"


class FinancialAdjustment(Base):
    __tablename__ = "financial_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    # Miesiąc raportowy, którego dotyczy korekta (1. dzień miesiąca).
    effective_month: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    # Rodzaj (wolny słownik: np. 'discount', 'bonus', 'invoice_correction').
    kind: Mapped[str] = mapped_column(String(50), nullable=False)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="PLN")
    description: Mapped[str] = mapped_column(Text, nullable=False)
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status: Mapped[AdjustmentStatus] = mapped_column(
        Enum(AdjustmentStatus, name="adjustmentstatus"),
        nullable=False,
        default=AdjustmentStatus.draft,
        index=True,
    )
    created_by: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    approved_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), nullable=True
    )
    approved_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<FinancialAdjustment id={self.id} {self.kind} {self.amount} "
            f"{self.currency} {self.status.value}>"
        )
