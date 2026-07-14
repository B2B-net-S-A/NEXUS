"""Scoring weight profiles — tunable hybrid-score layer budgets (Phase D1)."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    Text,
    UniqueConstraint,
    Index,
    func,
    text as sa_text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScoringWeightProfile(Base):
    __tablename__ = "scoring_weight_profiles"
    __table_args__ = (
        UniqueConstraint("name", name="uq_scoring_weight_profiles_name"),
        CheckConstraint(
            "NOT (user_id IS NOT NULL AND client_id IS NOT NULL)",
            name="ck_scoring_profile_single_scope",
        ),
        Index(
            "uq_scoring_profile_active_user",
            "user_id",
            unique=True,
            postgresql_where=sa_text("active AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_scoring_profile_active_client",
            "client_id",
            unique=True,
            postgresql_where=sa_text("active AND client_id IS NOT NULL"),
        ),
        Index(
            "uq_scoring_profile_active_global",
            sa_text("(1)"),
            unique=True,
            postgresql_where=sa_text(
                "active AND user_id IS NULL AND client_id IS NULL"
            ),
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    user_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    client_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=True, index=True
    )
    # Six weights, including champion_fit, must sum to 100.
    # Values must sum to 100 (enforced at API boundary via Pydantic).
    weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, server_default="true", nullable=False)
    version: Mapped[int] = mapped_column(Integer, server_default="1", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
