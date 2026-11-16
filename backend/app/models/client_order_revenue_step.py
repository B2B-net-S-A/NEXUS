"""Krok stawki przychodowej zamówienia od dnia (0721).

CHECK-i i indeksy muszą być identyczne z
``app/services/order_revenue_steps_schema.py`` (raport ``compare_metadata``
w ``/api/health/deep`` porównuje model z bazą). Reguły:
``app/services/order_revenue_steps.py``.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientOrderRevenueStep(Base):
    """Stawka przychodowa zamówienia obowiązująca od ``effective_from``."""

    __tablename__ = "client_order_revenue_steps"
    __table_args__ = (
        CheckConstraint("rate_client > 0", name="ck_client_order_revenue_steps_rate"),
        CheckConstraint(
            "md_rate_revenue IS NULL OR md_rate_revenue > 0",
            name="ck_client_order_revenue_steps_md",
        ),
        Index(
            "ux_client_order_revenue_steps_order_day",
            "order_id",
            "effective_from",
            unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), nullable=False
    )
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    # W jednostce i walucie zamówienia.
    rate_client: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    # PLN/MD — tylko gdy zamówienie ma stawkę MD.
    md_rate_revenue: Mapped[Optional[Decimal]] = mapped_column(
        Numeric(16, 3), nullable=True
    )
    contract_amendment_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("contract_amendments.id", ondelete="SET NULL"), nullable=True
    )
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
