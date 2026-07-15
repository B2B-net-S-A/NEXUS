"""Code-owned route registries. Database state may activate only these versions."""

from __future__ import annotations

from decimal import Decimal

from app.ai.types import AIError, FeatureRoute
from app.models.ai_feature import AIFeatureKey


def _r(
    provider: str,
    model: str,
    *,
    operation: str = "generate",
    timeout: float = 45.0,
    max_tokens: int = 2048,
    escalation: tuple[str, ...] = (),
    reserve: str = "0.25",
) -> FeatureRoute:
    return FeatureRoute(
        provider=provider,
        model=model,
        operation=operation,
        timeout_seconds=timeout,
        max_output_tokens=max_tokens,
        escalation_models=escalation,
        reservation_cost_usd=Decimal(reserve),
    )


# v1 mirrors the deployed behavior and remains the safe baseline. v2 exists in
# code but cannot become active without the audited activation endpoint.
V1_CURRENT: dict[AIFeatureKey, FeatureRoute | dict[str, FeatureRoute]] = {
    AIFeatureKey.embeddings: _r(
        "voyage", "voyage-3-large", operation="embed", reserve="0.02"
    ),
    AIFeatureKey.reranking: _r(
        "voyage", "rerank-2.5", operation="rerank", reserve="0.02"
    ),
    AIFeatureKey.matching: _r(
        "internal", "hybrid_score_v2", operation="deterministic", reserve="0"
    ),
    AIFeatureKey.cv_parser: _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    AIFeatureKey.job_writer: _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    AIFeatureKey.champion_profile: {
        "chunk": _r("anthropic", "claude-sonnet-5", max_tokens=2048),
        "synthesis": _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    },
    AIFeatureKey.candidate_summary: _r("anthropic", "claude-sonnet-5"),
    AIFeatureKey.match_explanation: _r(
        "internal", "score_breakdown_v1", operation="deterministic", reserve="0"
    ),
    AIFeatureKey.mindy: {
        "quick": _r("anthropic", "claude-sonnet-5"),
        "deep": _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    },
    AIFeatureKey.uop_analysis: _r("anthropic", "claude-sonnet-5"),
    AIFeatureKey.criteria_suggestions: _r("anthropic", "claude-sonnet-5"),
    AIFeatureKey.cv_b2b: _r("anthropic", "claude-sonnet-4-6", max_tokens=8192),
}

V2_TIERED: dict[AIFeatureKey, FeatureRoute | dict[str, FeatureRoute]] = {
    AIFeatureKey.embeddings: _r(
        "voyage", "voyage-4-large", operation="embed", reserve="0.02"
    ),
    AIFeatureKey.reranking: _r(
        "voyage", "rerank-2.5", operation="rerank", reserve="0.02"
    ),
    AIFeatureKey.matching: _r(
        "internal", "hybrid_score_v2", operation="deterministic", reserve="0"
    ),
    AIFeatureKey.cv_parser: _r(
        "anthropic",
        "claude-haiku-4-5",
        max_tokens=4096,
        escalation=("claude-sonnet-5",),
    ),
    AIFeatureKey.job_writer: _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    AIFeatureKey.champion_profile: {
        "chunk": _r("anthropic", "claude-haiku-4-5", max_tokens=2048),
        "synthesis": _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    },
    AIFeatureKey.candidate_summary: _r(
        "anthropic", "claude-haiku-4-5", escalation=("claude-sonnet-5",)
    ),
    AIFeatureKey.match_explanation: _r(
        "internal", "score_breakdown_v1", operation="deterministic", reserve="0"
    ),
    AIFeatureKey.mindy: {
        "quick": _r("anthropic", "claude-haiku-4-5"),
        "deep": _r("anthropic", "claude-sonnet-5", max_tokens=4096),
    },
    AIFeatureKey.uop_analysis: _r("anthropic", "claude-sonnet-5"),
    AIFeatureKey.criteria_suggestions: _r("anthropic", "claude-haiku-4-5"),
    AIFeatureKey.cv_b2b: _r("anthropic", "claude-sonnet-4-6", max_tokens=8192),
}

REGISTRIES = {"v1_current": V1_CURRENT, "v2_tiered": V2_TIERED}


def get_feature_route(
    registry_version: str, feature: AIFeatureKey, mode: str | None = None
) -> FeatureRoute:
    registry = REGISTRIES.get(registry_version)
    if registry is None:
        raise AIError(
            "unknown_registry", "Nieznana wersja routingu AI", status_code=409
        )
    route = registry.get(feature)
    if route is None:
        raise AIError("route_missing", "Brak routingu dla funkcji AI", status_code=503)
    if isinstance(route, dict):
        selected_mode = mode or "quick"
        selected = route.get(selected_mode)
        if selected is None:
            raise AIError(
                "invalid_mode", "Nieobsługiwany tryb funkcji AI", status_code=422
            )
        return selected
    return route


def public_registry(version: str) -> dict[str, dict[str, object]]:
    registry = REGISTRIES[version]
    output: dict[str, dict[str, object]] = {}
    for feature, route in registry.items():
        routes = route if isinstance(route, dict) else {"default": route}
        output[feature.value] = {
            "modes": {
                mode: {
                    "provider": item.provider,
                    "model": item.model,
                    "operation": item.operation,
                    "escalation_models": list(item.escalation_models),
                }
                for mode, item in routes.items()
            }
        }
    return output
