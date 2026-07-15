"""Scoring weight profiles — tunable hybrid-score layer budgets (Phase D1)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScoringWeightProfile(Base):
    __tablename__ = "scoring_weight_profiles"
    __table_args__ = (UniqueConstraint("name", name="uq_scoring_weight_profiles_name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Shape: {"semantic": 40, "skills": 30, "salary": 15, "location": 10, "availability": 5}
    # Values must sum to 100 (enforced at API boundary via Pydantic).
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
