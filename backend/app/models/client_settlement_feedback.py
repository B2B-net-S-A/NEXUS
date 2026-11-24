"""Informacja zwrotna o wadach rozliczenia (0774): wada × kontrakt × miesiąc.

CHECK-i, unikat i indeks jak w ``app/services/client_settlement_feedback_schema.py``
(strażnik dryfu schematu porównuje model z bazą po migracji).
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional

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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.services import client_settlement_feedback_schema as schema


class ClientSettlementFeedback(Base):
    __tablename__ = "client_settlement_feedback"
    __table_args__ = (
        UniqueConstraint(
            "contract_id",
            "period_month",
            "code",
            name="uq_client_settlement_feedback_defect",
        ),
        CheckConstraint(
            schema.CK_AUDIENCE, name="ck_client_settlement_feedback_audience"
        ),
        CheckConstraint(
            schema.CK_SENDS_ARRAY, name="ck_client_settlement_feedback_sends"
        ),
        CheckConstraint(
            schema.CK_SEND_COUNT, name="ck_client_settlement_feedback_count"
        ),
        Index("ix_client_settlement_feedback_month", "period_month", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contract_id: Mapped[int] = mapped_column(
        ForeignKey("contracts.id", ondelete="CASCADE"), nullable=False
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True
    )
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    code: Mapped[str] = mapped_column(String(schema.CODE_MAX), nullable=False)
    audience: Mapped[str] = mapped_column(String(12), nullable=False)
    detail: Mapped[Optional[str]] = mapped_column(
        String(schema.DETAIL_MAX), nullable=True
    )
    first_seen_on: Mapped[date] = mapped_column(Date, nullable=False)
    last_seen_on: Mapped[date] = mapped_column(Date, nullable=False)
    resolved_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    last_sent_on: Mapped[Optional[date]] = mapped_column(Date, nullable=True)
    send_count: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("0"), default=0
    )
    sends: Mapped[list[Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb"), default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
