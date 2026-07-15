"""Stable canary assignment and fail-closed rollback decisions."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.registry import REGISTRIES
from app.ai.types import AIRequest
from app.models.ai_rollout import (
    AIRolloutEvent,
    AIRolloutObservation,
    AIRolloutState,
)
from app.models.ai_platform import AIRoutingActivationLog, AIRoutingState


STAGES: tuple[tuple[str, int], ...] = (
    ("shadow", 0),
    ("5", 5),
    ("10", 10),
    ("25", 25),
    ("50", 50),
    ("100", 100),
)


def stable_bucket(request: AIRequest) -> int | None:
    identity = (
        f"client:{request.client_id}"
        if request.client_id is not None
        else f"user:{request.user_id}"
        if request.user_id is not None
        else f"{request.subject_type}:{request.subject_id}"
        if request.subject_type and request.subject_id is not None
        else None
    )
    if identity is None:
        return None
    digest = hashlib.sha256(
        f"{request.feature.value}:{identity}:canary-v1".encode()
    ).digest()
    return int.from_bytes(digest[:8], "big") % 100


def assigned_registry(
    state: AIRolloutState | None, request: AIRequest, *, global_registry: str
) -> str:
    if state is None or state.status != "active":
        return global_registry
    if (
        state.baseline_registry not in REGISTRIES
        or state.target_registry not in REGISTRIES
    ):
        return global_registry
    bucket = stable_bucket(request)
    if state.percentage <= 0 or bucket is None:
        return state.baseline_registry
    return (
        state.target_registry if bucket < state.percentage else state.baseline_registry
    )


def next_stage(stage: str) -> tuple[str, int] | None:
    for index, current in enumerate(STAGES):
        if current[0] == stage:
            return STAGES[index + 1] if index + 1 < len(STAGES) else None
    return None


def rollback_reasons(observation: AIRolloutObservation) -> list[str]:
    reasons: list[str] = []
    if observation.privacy_incidents > 0:
        reasons.append("privacy_incident")
    if observation.hallucination_samples > 0:
        rate = (
            100
            * observation.critical_hallucinations
            / observation.hallucination_samples
        )
        if rate > 0.5:
            reasons.append("critical_hallucination_rate")
    if observation.window_seconds >= 600 and observation.requests > 0:
        if 100 * observation.provider_errors / observation.requests > 1:
            reasons.append("provider_error_rate")
    if observation.p95_increase_pct > 50:
        reasons.append("p95_latency")
    if observation.cost_increase_pct > 25:
        reasons.append("cost")
    if observation.recall_at_20_drop_pp > 1:
        reasons.append("recall_at_20")
    if observation.ndcg_at_10_drop_pct > 3:
        reasons.append("ndcg_at_10")
    if observation.worst_slice_drop_pp > 3:
        reasons.append("important_slice")
    return reasons


async def _rollback_indexes(state: AIRolloutState) -> None:
    if not state.baseline_index_targets or not state.target_index_targets:
        return
    from app.services.qdrant_factory import get_qdrant_client
    from app.services.qdrant_migration import rollback_aliases

    def run() -> None:
        client = get_qdrant_client()
        rollback_aliases(
            client,
            state.baseline_index_targets,
            expected_current=state.target_index_targets,
        )

    await asyncio.to_thread(run)


async def rollback(
    db: AsyncSession,
    state: AIRolloutState,
    *,
    reason: str,
    actor_id: int | None,
    automatic: bool,
) -> None:
    # During the 14-day retention window a rollback also restores the global
    # route activated by completion. Active canaries already use the baseline
    # as the global route, so they need no routing-state mutation here.
    if state.status == "completed":
        routing = await db.scalar(
            select(AIRoutingState).where(AIRoutingState.id == 1).with_for_update()
        )
        if routing is not None and routing.registry_version == state.target_registry:
            previous_registry = routing.registry_version
            routing.registry_version = state.baseline_registry
            routing.lock_version += 1
            routing.reason = reason
            routing.activated_by = actor_id
            routing.activated_at = datetime.now(timezone.utc)
            db.add(
                AIRoutingActivationLog(
                    previous_version=previous_registry,
                    registry_version=state.baseline_registry,
                    lock_version=routing.lock_version,
                    reason=reason,
                    activated_by=actor_id,
                )
            )
    index_error: str | None = None
    try:
        await _rollback_indexes(state)
    except Exception as exc:  # noqa: BLE001 - route rollback must still happen
        index_error = type(exc).__name__
    previous_stage = state.stage
    state.status = "rolled_back"
    state.percentage = 0
    state.rollback_reason = reason
    state.lock_version += 1
    db.add(
        AIRolloutEvent(
            feature=state.feature,
            event="auto_rollback" if automatic else "manual_rollback",
            from_stage=previous_stage,
            to_stage="baseline",
            reason=reason,
            actor_id=actor_id,
            metadata_json={"index_rollback_error": index_error} if index_error else {},
        )
    )


async def evaluate_observation(
    db: AsyncSession, state: AIRolloutState, observation: AIRolloutObservation
) -> list[str]:
    reasons = rollback_reasons(observation)
    rollback_window_open = bool(
        state.status == "active"
        or (
            state.status == "completed"
            and state.rollback_available_until
            and state.rollback_available_until > datetime.now(timezone.utc)
        )
    )
    if reasons and rollback_window_open:
        await rollback(
            db,
            state,
            reason=",".join(reasons),
            actor_id=None,
            automatic=True,
        )
    return reasons


async def evaluate_active_rollouts(db: AsyncSession) -> int:
    now = datetime.now(timezone.utc)
    states = (
        await db.scalars(
            select(AIRolloutState).where(
                or_(
                    AIRolloutState.status == "active",
                    (
                        (AIRolloutState.status == "completed")
                        & (AIRolloutState.rollback_available_until > now)
                    ),
                )
            )
        )
    ).all()
    rolled_back = 0
    for state in states:
        observation = await db.scalar(
            select(AIRolloutObservation)
            .where(
                AIRolloutObservation.feature == state.feature,
                AIRolloutObservation.created_at >= state.stage_started_at,
            )
            .order_by(AIRolloutObservation.id.desc())
            .limit(1)
        )
        if observation and await evaluate_observation(db, state, observation):
            rolled_back += 1
    return rolled_back


def completion_windows(now: datetime | None = None) -> dict[str, datetime]:
    now = now or datetime.now(timezone.utc)
    return {
        "rollback_available_until": now + timedelta(days=14),
        "monitoring_until": now + timedelta(weeks=4),
        "next_regression_at": now + timedelta(days=30),
    }
