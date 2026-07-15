"""Audited canary rollout state, observations and reports."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AIRolloutState(Base):
    __tablename__ = "ai_rollout_state"

    feature: Mapped[str] = mapped_column(String(64), primary_key=True)
    baseline_registry: Mapped[str] = mapped_column(String(64), nullable=False)
    target_registry: Mapped[str] = mapped_column(String(64), nullable=False)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="shadow")
    percentage: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    min_stage_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=72)
    lock_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    offline_gate_reference: Mapped[str] = mapped_column(String(256), nullable=False)
    baseline_index_targets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    target_index_targets: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    rollback_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    started_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    stage_started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rollback_available_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    monitoring_until: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    next_regression_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AIRolloutObservation(Base):
    __tablename__ = "ai_rollout_observations"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    registry_version: Mapped[str] = mapped_column(String(64), nullable=False)
    window_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    requests: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    provider_errors: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    privacy_incidents: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    critical_hallucinations: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    hallucination_samples: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    p95_increase_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    cost_increase_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    recall_at_20_drop_pp: Mapped[float] = mapped_column(
        Float, nullable=False, default=0
    )
    ndcg_at_10_drop_pct: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    worst_slice_drop_pp: Mapped[float] = mapped_column(Float, nullable=False, default=0)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )


class AIRolloutEvent(Base):
    __tablename__ = "ai_rollout_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    event: Mapped[str] = mapped_column(String(32), nullable=False)
    from_stage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    to_stage: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    actor_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AIRolloutReport(Base):
    __tablename__ = "ai_rollout_reports"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    feature: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    report_type: Mapped[str] = mapped_column(String(20), nullable=False)
    period_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    period_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    quality_passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    artifact_ref: Mapped[str] = mapped_column(String(512), nullable=False)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
