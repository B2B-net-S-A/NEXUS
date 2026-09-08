"""Append-only metering. No candidate content, prompts or credentials.

Actor keys are immutable IDs (system/user:<id>), deliberately not nullable FKs:
deleting a user must not merge their history with system operations. Legacy
ai_usage_log is preserved verbatim and never used as trustworthy token usage.
"""

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIOperation(Base):
    __tablename__ = "ai_operations"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    feature: Mapped[str] = mapped_column(String(64), index=True)
    actor_key: Mapped[str] = mapped_column(String(48))
    period_start: Mapped[date] = mapped_column(Date, index=True)
    units: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class AIProviderCall(Base):
    __tablename__ = "ai_provider_calls"
    # Provider message ID when available, otherwise a UUID generated once.
    event_key: Mapped[str] = mapped_column(String(200), primary_key=True)
    operation_id: Mapped[str] = mapped_column(
        ForeignKey("ai_operations.id"), index=True
    )
    provider: Mapped[str] = mapped_column(String(32))
    model: Mapped[str] = mapped_column(String(100))
    request_id: Mapped[str | None] = mapped_column(String(128))
    outcome: Mapped[str] = mapped_column(String(32))
    latency_ms: Mapped[int] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(BigInteger)
    output_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_read_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_creation_tokens: Mapped[int | None] = mapped_column(BigInteger)
    cache_creation_1h_tokens: Mapped[int | None] = mapped_column(BigInteger)
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(18, 8))
    price_version: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AIGenerationLease(Base):
    __tablename__ = "ai_generation_leases"
    key: Mapped[str] = mapped_column(String(128), primary_key=True)
    token: Mapped[str] = mapped_column(String(36))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AISpendAlert(Base):
    __tablename__ = "ai_spend_alerts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(180), unique=True)
    message: Mapped[str] = mapped_column(String(2000))
    recipient_id: Mapped[int | None] = mapped_column(Integer)
    in_app_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    slack_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
