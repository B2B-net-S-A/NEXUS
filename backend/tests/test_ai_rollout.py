from __future__ import annotations

from datetime import datetime, timezone

from pydantic import ValidationError
import pytest

from app.ai.types import AIRequest
from app.api.ai_rollouts import RolloutStart
from app.models.ai_feature import AIFeatureKey
from app.models.ai_rollout import AIRolloutObservation, AIRolloutState
from app.services.ai_rollout import (
    STAGES,
    assigned_registry,
    completion_windows,
    next_stage,
    rollback_reasons,
    stable_bucket,
)
from app.services.qdrant_factory import ACTIVE_ALIASES


def request(*, user_id=None, client_id=None, subject_id=None) -> AIRequest:
    return AIRequest(
        feature=AIFeatureKey.cv_parser,
        messages=[],
        user_id=user_id,
        client_id=client_id,
        subject_type="candidate" if subject_id else None,
        subject_id=subject_id,
    )


def state(*, percentage: int = 10, status: str = "active") -> AIRolloutState:
    return AIRolloutState(
        feature="cv_parser",
        baseline_registry="v1_current",
        target_registry="v2_tiered",
        stage=str(percentage) if percentage else "shadow",
        percentage=percentage,
        status=status,
        min_stage_hours=72,
        lock_version=1,
        offline_gate_reference="eval:1",
        baseline_index_targets={},
        target_index_targets={},
        reason="test rollout",
        started_at=datetime.now(timezone.utc),
        stage_started_at=datetime.now(timezone.utc),
    )


def observation(**overrides) -> AIRolloutObservation:
    values = {
        "feature": "cv_parser",
        "registry_version": "v2_tiered",
        "window_seconds": 600,
        "requests": 1000,
        "provider_errors": 0,
        "privacy_incidents": 0,
        "critical_hallucinations": 0,
        "hallucination_samples": 1000,
        "p95_increase_pct": 0,
        "cost_increase_pct": 0,
        "recall_at_20_drop_pp": 0,
        "ndcg_at_10_drop_pct": 0,
        "worst_slice_drop_pp": 0,
        "source": "test",
    }
    values.update(overrides)
    return AIRolloutObservation(**values)


def test_canary_assignment_is_stable_and_client_first() -> None:
    first = request(user_id=7, client_id=3)
    second = request(user_id=99, client_id=3)
    assert stable_bucket(first) == stable_bucket(second)
    assert stable_bucket(first) == stable_bucket(first)


def test_anonymous_system_call_stays_on_baseline() -> None:
    item = request()
    assert stable_bucket(item) is None
    assert (
        assigned_registry(state(percentage=100), item, global_registry="v1_current")
        == "v1_current"
    )


def test_rollout_uses_target_only_inside_bucket() -> None:
    item = request(user_id=42)
    bucket = stable_bucket(item)
    assert bucket is not None
    expected = "v2_tiered" if bucket < 50 else "v1_current"
    assert (
        assigned_registry(state(percentage=50), item, global_registry="v1_current")
        == expected
    )
    assert (
        assigned_registry(state(percentage=0), item, global_registry="v1_current")
        == "v1_current"
    )


@pytest.mark.parametrize(
    ("overrides", "reason"),
    [
        ({"privacy_incidents": 1}, "privacy_incident"),
        ({"critical_hallucinations": 6}, "critical_hallucination_rate"),
        ({"provider_errors": 11}, "provider_error_rate"),
        ({"p95_increase_pct": 50.1}, "p95_latency"),
        ({"cost_increase_pct": 25.1}, "cost"),
        ({"recall_at_20_drop_pp": 1.1}, "recall_at_20"),
        ({"ndcg_at_10_drop_pct": 3.1}, "ndcg_at_10"),
        ({"worst_slice_drop_pp": 3.1}, "important_slice"),
    ],
)
def test_each_guardrail_triggers_rollback(overrides, reason) -> None:
    assert reason in rollback_reasons(observation(**overrides))


def test_provider_error_requires_ten_minute_window() -> None:
    assert "provider_error_rate" not in rollback_reasons(
        observation(window_seconds=599, provider_errors=100)
    )


def test_rollout_stages_are_fixed_and_non_skippable() -> None:
    assert STAGES == (
        ("shadow", 0),
        ("5", 5),
        ("10", 10),
        ("25", 25),
        ("50", 50),
        ("100", 100),
    )
    assert next_stage("shadow") == ("5", 5)
    assert next_stage("100") is None


def test_index_snapshots_must_be_complete_pairs() -> None:
    aliases = {alias: f"old-{entity}" for entity, alias in ACTIVE_ALIASES.items()}
    with pytest.raises(ValidationError):
        RolloutStart(
            feature=AIFeatureKey.matching,
            baseline_registry="v1_current",
            target_registry="v2_tiered",
            offline_gate_passed=True,
            offline_gate_reference="gold:1",
            reason="validated matching rollout",
            baseline_index_targets=aliases,
        )


def test_completion_retains_rollback_for_fourteen_days() -> None:
    now = datetime.now(timezone.utc)
    windows = completion_windows(now)
    assert (windows["rollback_available_until"] - now).days == 14
    assert (windows["monitoring_until"] - now).days == 28
