"""Dziennik przypomnień o brakującym raporcie godzin (0763).

CHECK-i, unikat i indeks jak w ``app/services/client_settlement_reminders_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import client_settlement_reminders_schema as schema


class ClientSettlementReminder(Base):
    __tablename__ = "client_settlement_reminders"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "period_month",
            "channel",
            "sent_on",
            name="uq_client_settlement_reminders_day",
        ),
        CheckConstraint(schema.CK_STEP, name="ck_client_settlement_reminders_step"),
        CheckConstraint(
            schema.CK_CHANNEL, name="ck_client_settlement_reminders_channel"
        ),
        CheckConstraint(
            schema.CK_OUTCOME, name="ck_client_settlement_reminders_outcome"
        ),
        Index("ix_client_settlement_reminders_month", "period_month", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    step: Mapped[str] = mapped_column(String(8), nullable=False)
    channel: Mapped[str] = mapped_column(String(12), nullable=False)
    owner_user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    outcome: Mapped[str] = mapped_column(
        String(12), nullable=False, server_default=text("'pending'"), default="pending"
    )
    sent_on: Mapped[date] = mapped_column(Date, nullable=False)
    sent_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
