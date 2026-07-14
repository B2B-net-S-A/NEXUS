"""Typed, scope-isolated cache helpers for analytics v1 responses."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from app.analytics.capabilities import analytics_capability_values
from app.analytics.periods import AnalyticsPeriod
from app.analytics.schemas import METRIC_VERSION
from app.core.cache import cache_get, cache_invalidate, cache_set
from app.models.user import UserRole


class AnalyticsCacheUser(Protocol):
    role: UserRole

    def get_all_roles(self) -> set[UserRole]: ...


ModelT = TypeVar("ModelT", bound=BaseModel)


def analytics_cache_key(
    metric: str,
    *,
    user: AnalyticsCacheUser,
    scope: str,
    period: AnalyticsPeriod,
    params: dict[str, Any] | None = None,
) -> str:
    """Build a deterministic key with every authorization/data dimension."""

    capabilities = ",".join(analytics_capability_values(user)) or "none"
    serialized_params = json.dumps(
        params or {},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    params_digest = hashlib.sha256(serialized_params.encode("utf-8")).hexdigest()[:16]
    return (
        f"analytics:v1:{METRIC_VERSION}:{metric}:caps={capabilities}:"
        f"scope={scope}:start={period.start.isoformat()}:"
        f"end={period.end.isoformat()}:params={params_digest}"
    )


async def analytics_cache_get(key: str, model: type[ModelT]) -> ModelT | None:
    """Load and validate cached JSON against the current typed contract."""

    cached = await cache_get(key)
    if cached is None:
        return None
    try:
        return model.model_validate(cached)
    except (TypeError, ValueError, ValidationError):
        # Contract drift must become a miss, never a 500 or a stale response.
        await cache_invalidate(key)
        return None


async def analytics_cache_set(
    key: str,
    value: BaseModel,
    *,
    ttl_seconds: int,
) -> None:
    await cache_set(
        key,
        value.model_dump(mode="json"),
        ttl_seconds=ttl_seconds,
    )


async def invalidate_analytics_cache() -> None:
    """Invalidate every metric version after an audited finance mutation."""

    await cache_invalidate("analytics:v1:")
