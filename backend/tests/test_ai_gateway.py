from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.ai.adapters import ADAPTERS, AdapterResponse
from app.ai.circuit_breaker import CircuitBreaker, circuit_breaker
from app.ai.gateway import AIGateway
from app.ai.registry import REGISTRIES, get_feature_route
from app.ai.types import AIError, AIRequest
from app.models.ai_feature import AIFeatureKey
from app.models.ai_platform import AICallLedger
from app.schemas.ai_settings import FeatureConfigUpdate


def test_all_escalations_stay_within_the_declared_provider() -> None:
    for registry in REGISTRIES.values():
        for configured in registry.values():
            routes = (
                configured.values() if isinstance(configured, dict) else [configured]
            )
            for route in routes:
                assert route.provider in {"anthropic", "voyage", "internal", "openai"}
                assert all(model for model in route.escalation_models)


def test_mindy_mode_is_selected_by_the_caller() -> None:
    quick = get_feature_route("v2_tiered", AIFeatureKey.mindy, "quick")
    deep = get_feature_route("v2_tiered", AIFeatureKey.mindy, "deep")
    assert quick.model == "claude-haiku-4-5"
    assert deep.model == "claude-sonnet-5"
    with pytest.raises(AIError) as exc:
        get_feature_route("v2_tiered", AIFeatureKey.mindy, "automatic")
    assert exc.value.code == "invalid_mode"


def test_settings_patch_rejects_provider_or_model() -> None:
    with pytest.raises(ValidationError):
        FeatureConfigUpdate.model_validate({"enabled": True, "provider": "openai"})
    with pytest.raises(ValidationError):
        FeatureConfigUpdate.model_validate({"monthly_limit": 10, "model": "anything"})


def test_ledger_has_no_prompt_or_response_payload_columns() -> None:
    columns = set(AICallLedger.__table__.columns.keys())
    assert "prompt" not in columns
    assert "response" not in columns
    assert {"input_hash", "output_hash", "pii", "cost_usd"}.issubset(columns)


def test_circuit_breaker_opens_after_three_failures() -> None:
    breaker = CircuitBreaker(failure_threshold=3, cooldown_seconds=60)
    for _ in range(3):
        breaker.failure("anthropic:model")
    assert breaker.allow("anthropic:model") is False


@pytest.mark.asyncio
async def test_gateway_retries_transient_error_once(monkeypatch) -> None:
    gateway = AIGateway()
    calls = 0
    ledger_rows: list[dict] = []

    class FakeAdapter:
        async def call(self, request, route, *, model):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AIError("provider_error", "temporary", retryable=True)
            return AdapterResponse(
                content='{"ok": true}',
                input_tokens=12,
                output_tokens=4,
                cost_usd=Decimal("0.01"),
            )

    async def no_authorize(*args, **kwargs):
        return None

    async def capture_ledger(*args, **kwargs):
        ledger_rows.append(kwargs)

    async def no_reconcile(*args, **kwargs):
        return None

    async def active_version(_request):
        return "v1_current"

    monkeypatch.setitem(ADAPTERS, "anthropic", FakeAdapter())
    monkeypatch.setattr(gateway, "_authorize_and_reserve", no_authorize)
    monkeypatch.setattr(gateway, "_ledger", capture_ledger)
    monkeypatch.setattr(gateway, "_reconcile", no_reconcile)
    monkeypatch.setattr(gateway, "_registry_version_for_request", active_version)
    circuit_breaker.success("anthropic:claude-sonnet-5")

    result = await gateway.call(
        AIRequest(
            feature=AIFeatureKey.cv_parser,
            messages=[{"role": "user", "content": "test"}],
            pii=True,
            structured_validator=lambda value: value,
        )
    )

    assert calls == 2
    assert result.content == {"ok": True}
    assert result.cost_usd == Decimal("0.01")
    assert [row["status"] for row in ledger_rows] == ["error", "success"]
    assert ledger_rows[1]["retried"] is True
