"""Koszt zamówienia od dnia zmiany stawki Partnera (0741).

CHECK-i i indeksy muszą być identyczne z ``app/services/order_cost_steps_schema.py``
(raport ``compare_metadata`` w ``/api/health/deep`` porównuje model z bazą).
Reguły: ``app/services/order_cost_steps.py``.
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
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ClientOrderCostStep(Base):
    """Stawka kosztowa zamówienia obowiązująca od ``effective_from``."""

    __tablename__ = "client_order_cost_steps"
    __table_args__ = (
        CheckConstraint("rate_candidate > 0", name="ck_client_order_cost_steps_rate"),
        CheckConstraint(
            "source IN ('contract', 'finance')",
            name="ck_client_order_cost_steps_source",
        ),
        Index(
            "ux_client_order_cost_steps_order_day",
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
    rate_candidate: Mapped[Decimal] = mapped_column(Numeric(16, 3), nullable=False)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClientOrderCostReview(Base):
    """„Zostaw” Finansów dla zakończonego zamówienia przy danym harmonogramie."""

    __tablename__ = "client_order_cost_reviews"

    order_id: Mapped[int] = mapped_column(
        ForeignKey("client_orders.id", ondelete="CASCADE"), primary_key=True
    )
    signature: Mapped[str] = mapped_column(String(64), nullable=False)
    decided_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
