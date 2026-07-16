"""Cache Analytics v1 (plan §4.6).

Klucz cache MUSI zawierać co najmniej: wersję metryk, endpoint/moduł,
zestaw capabilities, scope, okres (start/end/tz) i wszystkie filtry
wpływające na wynik. Nie wolno cache'ować odpowiedzi managerskiej lub
finansowej pod kluczem współdzielonym z viewer-safe — dlatego capability
set jest twardym składnikiem klucza, a helpery nie przyjmują klucza
zbudowanego ręcznie.

Backend = istniejący in-memory TTL cache (app.core.cache). Wymiana na
Redis w przyszłości nie zmienia kontraktu klucza.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from typing import Any

from app.analytics.capabilities import AnalyticsCapability
from app.analytics.periods import Period
from app.analytics.scope import Scope
from app.core.cache import cache_get, cache_set

# Wersja definicji metryk — bump przy KAŻDEJ zmianie semantyki metryk
# unieważnia cały cache analytics (klucz zawiera wersję).
METRIC_VERSION = "2026-07-16.1"

_PREFIX = "analytics:v1"


def build_cache_key(
    endpoint: str,
    *,
    capabilities: Iterable[AnalyticsCapability],
    scope: Scope,
    period: Period,
    filters: dict[str, Any] | None = None,
    metric_version: str = METRIC_VERSION,
) -> str:
    """Deterministyczny klucz cache spełniający kontrakt §4.6.

    ``filters`` jest serializowane kanonicznie (sort_keys) i hashowane —
    długie kombinacje filtrów nie rozdmuchują klucza, a każda zmiana
    filtra daje inny klucz.
    """
    caps_token = ",".join(sorted(c.value for c in capabilities))
    filters_json = json.dumps(
        filters or {}, sort_keys=True, ensure_ascii=False, default=str
    )
    raw = "|".join(
        [
            metric_version,
            endpoint,
            caps_token,
            scope.cache_token(),
            period.kind.value,
            period.start.isoformat(),
            period.end.isoformat(),
            period.timezone,
            filters_json,
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]
    # Prefiks czytelny do debugowania + digest gwarantujący unikalność.
    return f"{_PREFIX}:{endpoint}:{digest}"


async def analytics_cache_get(key: str) -> Any | None:
    if not key.startswith(_PREFIX):  # pragma: no cover — błąd programisty
        raise ValueError("Analytics cache requires a build_cache_key() key")
    return await cache_get(key)


async def analytics_cache_set(key: str, value: Any, ttl_seconds: int) -> None:
    if not key.startswith(_PREFIX):  # pragma: no cover — błąd programisty
        raise ValueError("Analytics cache requires a build_cache_key() key")
    await cache_set(key, value, ttl_seconds=ttl_seconds)
