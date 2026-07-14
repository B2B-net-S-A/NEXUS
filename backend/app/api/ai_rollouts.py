"""Administrator control plane for staged AI canaries and rollback."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import REGISTRIES
from app.api.deps import AdminUser
from app.core.database import get_db
from app.models.ai_feature import AIFeatureKey
from app.models.ai_platform import AIRoutingActivationLog, AIRoutingState
from app.models.ai_rollout import (
    AIRolloutEvent,
    AIRolloutObservation,
    AIRolloutReport,
    AIRolloutState,
)
from app.services.ai_rollout import (
    completion_windows,
    evaluate_observation,
    next_stage,
    rollback,
)
from app.services.qdrant_factory import ACTIVE_ALIASES


router = APIRouter(prefix="/admin/ai-rollouts", tags=["admin-ai-rollouts"])


class RolloutStart(BaseModel):
    feature: AIFeatureKey
    baseline_registry: str
    target_registry: str
    offline_gate_passed: bool
    offline_gate_reference: str = Field(min_length=5, max_length=256)
    reason: str = Field(min_length=10, max_length=1000)
    min_stage_hours: int = Field(default=72, ge=48, le=72)
    baseline_index_targets: dict[str, str] = Field(default_factory=dict)
    target_index_targets: dict[str, str] = Field(default_factory=dict)
    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_index_snapshots(self):
        expected = set(ACTIVE_ALIASES.values())
        for snapshot in (self.baseline_index_targets, self.target_index_targets):
            if snapshot and set(snapshot) != expected:
                raise ValueError("index snapshots must contain all four active aliases")
        if bool(self.baseline_index_targets) != bool(self.target_index_targets):
            raise ValueError("both index snapshots are required together")
        return self


class RolloutMutation(BaseModel):
    expected_lock_version: int = Field(ge=1)
    reason: str = Field(min_length=10, max_length=1000)
    model_config = {"extra": "forbid"}


class RolloutObservationIn(BaseModel):
    registry_version: str
    window_seconds: int = Field(ge=1, le=604800)
    requests: int = Field(ge=0)
    provider_errors: int = Field(ge=0)
    privacy_incidents: int = Field(default=0, ge=0)
    critical_hallucinations: int = Field(default=0, ge=0)
    hallucination_samples: int = Field(default=0, ge=0)
    p95_increase_pct: float = 0
    cost_increase_pct: float = 0
    recall_at_20_drop_pp: float = 0
    ndcg_at_10_drop_pct: float = 0
    worst_slice_drop_pp: float = 0
    source: str = Field(min_length=2, max_length=64)
    model_config = {"extra": "forbid"}


class RolloutReportIn(BaseModel):
    report_type: Literal["weekly", "monthly_regression"]
    period_start: datetime
    period_end: datetime
    quality_passed: bool
    artifact_ref: str = Field(min_length=3, max_length=512)
    notes: str | None = Field(default=None, max_length=2000)
    model_config = {"extra": "forbid"}


def _state_payload(row: AIRolloutState) -> dict[str, Any]:
    return {
        "feature": row.feature,
        "baseline_registry": row.baseline_registry,
        "target_registry": row.target_registry,
        "stage": row.stage,
        "percentage": row.percentage,
        "status": row.status,
        "lock_version": row.lock_version,
        "stage_started_at": row.stage_started_at,
        "rollback_reason": row.rollback_reason,
        "rollback_available_until": row.rollback_available_until,
        "monitoring_until": row.monitoring_until,
        "next_regression_at": row.next_regression_at,
        "cleanup_eligible": bool(
            row.status == "completed"
            and row.rollback_available_until
            and row.rollback_available_until <= datetime.now(timezone.utc)
        ),
    }


@router.get("")
async def list_rollouts(
    admin: AdminUser, db: AsyncSession = Depends(get_db)
) -> list[dict[str, Any]]:
    del admin
    rows = (
        await db.scalars(select(AIRolloutState).order_by(AIRolloutState.feature))
    ).all()
    return [_state_payload(row) for row in rows]


@router.post("/start", status_code=201)
async def start_rollout(
    payload: RolloutStart,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    if not payload.offline_gate_passed:
        raise HTTPException(status_code=422, detail="Offline quality gate must pass")
    if (
        payload.baseline_registry not in REGISTRIES
        or payload.target_registry not in REGISTRIES
    ):
        raise HTTPException(status_code=422, detail="Unknown code-owned registry")
    if payload.baseline_registry == payload.target_registry:
        raise HTTPException(status_code=422, detail="Baseline and target must differ")
    current = await db.get(AIRolloutState, payload.feature.value)
    if current and current.status == "active":
        raise HTTPException(status_code=409, detail="Active rollout already exists")
    now = datetime.now(timezone.utc)
    row = AIRolloutState(
        feature=payload.feature.value,
        baseline_registry=payload.baseline_registry,
        target_registry=payload.target_registry,
        stage="shadow",
        percentage=0,
        status="active",
        min_stage_hours=payload.min_stage_hours,
        lock_version=(current.lock_version + 1) if current else 1,
        offline_gate_reference=payload.offline_gate_reference,
        baseline_index_targets=payload.baseline_index_targets,
        target_index_targets=payload.target_index_targets,
        reason=payload.reason,
        rollback_reason=None,
        started_by=admin.id,
        started_at=now,
        stage_started_at=now,
        completed_at=None,
        rollback_available_until=None,
        monitoring_until=None,
        next_regression_at=None,
    )
    await db.merge(row)
    db.add(
        AIRolloutEvent(
            feature=row.feature,
            event="started",
            from_stage="offline",
            to_stage="shadow",
            reason=payload.reason,
            actor_id=admin.id,
            metadata_json={"offline_gate_reference": payload.offline_gate_reference},
        )
    )
    await db.commit()
    return _state_payload(row)


@router.post("/{feature}/advance")
async def advance_rollout(
    feature: AIFeatureKey,
    payload: RolloutMutation,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(AIRolloutState)
        .where(AIRolloutState.feature == feature.value)
        .with_for_update()
    )
    if row is None or row.status != "active":
        raise HTTPException(status_code=404, detail="Active rollout not found")
    if row.lock_version != payload.expected_lock_version:
        raise HTTPException(status_code=409, detail={"lock_version": row.lock_version})
    elapsed = datetime.now(timezone.utc) - row.stage_started_at
    minimum = timedelta(hours=row.min_stage_hours)
    if elapsed < minimum:
        raise HTTPException(
            status_code=409,
            detail={
                "message": "Minimum stage duration not met",
                "remaining_seconds": int((minimum - elapsed).total_seconds()),
            },
        )
    following = next_stage(row.stage)
    if following is None:
        raise HTTPException(
            status_code=409, detail="100% stage must be completed, not advanced"
        )
    previous = row.stage
    row.stage, row.percentage = following
    row.stage_started_at = datetime.now(timezone.utc)
    row.lock_version += 1
    db.add(
        AIRolloutEvent(
            feature=row.feature,
            event="advanced",
            from_stage=previous,
            to_stage=row.stage,
            reason=payload.reason,
            actor_id=admin.id,
            metadata_json={"percentage": row.percentage},
        )
    )
    await db.commit()
    return _state_payload(row)


@router.post("/{feature}/observations", status_code=201)
async def add_observation(
    feature: AIFeatureKey,
    payload: RolloutObservationIn,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(AIRolloutState)
        .where(AIRolloutState.feature == feature.value)
        .with_for_update()
    )
    rollback_window_open = bool(
        row
        and row.status == "completed"
        and row.rollback_available_until
        and row.rollback_available_until > datetime.now(timezone.utc)
    )
    if row is None or (row.status != "active" and not rollback_window_open):
        raise HTTPException(status_code=404, detail="Active rollout not found")
    if payload.registry_version != row.target_registry:
        raise HTTPException(
            status_code=422, detail="Observation must describe target registry"
        )
    observation = AIRolloutObservation(
        feature=feature.value, created_by=admin.id, **payload.model_dump()
    )
    db.add(observation)
    await db.flush()
    reasons = await evaluate_observation(db, row, observation)
    await db.commit()
    return {
        "observation_id": observation.id,
        "rollback": bool(reasons),
        "reasons": reasons,
        "state": _state_payload(row),
    }


@router.post("/{feature}/rollback")
async def manual_rollback(
    feature: AIFeatureKey,
    payload: RolloutMutation,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(AIRolloutState)
        .where(AIRolloutState.feature == feature.value)
        .with_for_update()
    )
    rollback_window_open = bool(
        row
        and row.status == "completed"
        and row.rollback_available_until
        and row.rollback_available_until > datetime.now(timezone.utc)
    )
    if row is None or (row.status != "active" and not rollback_window_open):
        raise HTTPException(status_code=404, detail="Active rollout not found")
    if row.lock_version != payload.expected_lock_version:
        raise HTTPException(status_code=409, detail={"lock_version": row.lock_version})
    await rollback(db, row, reason=payload.reason, actor_id=admin.id, automatic=False)
    await db.commit()
    return _state_payload(row)


@router.post("/{feature}/complete")
async def complete_rollout(
    feature: AIFeatureKey,
    payload: RolloutMutation,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.scalar(
        select(AIRolloutState)
        .where(AIRolloutState.feature == feature.value)
        .with_for_update()
    )
    if row is None or row.status != "active" or row.stage != "100":
        raise HTTPException(status_code=409, detail="Rollout must be active at 100%")
    if row.lock_version != payload.expected_lock_version:
        raise HTTPException(status_code=409, detail={"lock_version": row.lock_version})
    elapsed = datetime.now(timezone.utc) - row.stage_started_at
    if elapsed < timedelta(hours=row.min_stage_hours):
        raise HTTPException(
            status_code=409, detail="Minimum 100% observation window not met"
        )
    routing = await db.scalar(
        select(AIRoutingState).where(AIRoutingState.id == 1).with_for_update()
    )
    if routing is None or routing.registry_version != row.baseline_registry:
        raise HTTPException(
            status_code=409, detail="Global route changed during canary"
        )
    previous_registry = routing.registry_version
    routing.registry_version = row.target_registry
    routing.lock_version += 1
    routing.reason = payload.reason
    routing.activated_by = admin.id
    routing.activated_at = datetime.now(timezone.utc)
    db.add(
        AIRoutingActivationLog(
            previous_version=previous_registry,
            registry_version=routing.registry_version,
            lock_version=routing.lock_version,
            reason=payload.reason,
            activated_by=admin.id,
        )
    )
    row.status = "completed"
    row.completed_at = datetime.now(timezone.utc)
    row.lock_version += 1
    for key, value in completion_windows(row.completed_at).items():
        setattr(row, key, value)
    db.add(
        AIRolloutEvent(
            feature=row.feature,
            event="completed",
            from_stage="100",
            to_stage="global",
            reason=payload.reason,
            actor_id=admin.id,
            metadata_json={"registry_version": row.target_registry},
        )
    )
    await db.commit()
    return _state_payload(row)


@router.post("/{feature}/reports", status_code=201)
async def add_rollout_report(
    feature: AIFeatureKey,
    payload: RolloutReportIn,
    admin: AdminUser,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    row = await db.get(AIRolloutState, feature.value)
    if row is None:
        raise HTTPException(status_code=404, detail="Rollout not found")
    report = AIRolloutReport(
        feature=feature.value, created_by=admin.id, **payload.model_dump()
    )
    db.add(report)
    if payload.report_type == "monthly_regression":
        row.next_regression_at = payload.period_end + timedelta(days=30)
    await db.commit()
    return {"id": report.id, "quality_passed": report.quality_passed}
