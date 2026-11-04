"""Panel wag rankingu (0501): historia zmian i pomiary szkicu na historii."""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class ScoringWeightChange(Base):
    __tablename__ = "scoring_weight_changes"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('publish', 'admin_edit')",
            name="ck_scoring_weight_changes_kind",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    profile_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # {"panel": {semantic, skills, location}, "threshold": 70, "weights": {...}}
    before: Mapped[dict] = mapped_column(JSONB, nullable=False)
    after: Mapped[dict] = mapped_column(JSONB, nullable=False)
    reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    measurement: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


class ScoringWeightMeasurement(Base):
    __tablename__ = "scoring_weight_measurements"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'done', 'failed')",
            name="ck_scoring_weight_measurements_status",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="queued"
    )
    requested_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    # Ważności panelu: {"semantic", "skills", "location", "threshold"}.
    baseline: Mapped[dict] = mapped_column(JSONB, nullable=False)
    draft: Mapped[dict] = mapped_column(JSONB, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    progress: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    result: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
