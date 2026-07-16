"""Testy izolacji cache Analytics v1 (plan PR 2 / §4.6).

Klucz cache musi się różnić przy zmianie: wersji metryk, endpointu,
zestawu capabilities, scope'u, okresu i filtrów. Odpowiedź managerska /
finansowa nigdy nie może współdzielić klucza z viewer-safe.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from app.analytics.cache import (
    METRIC_VERSION,
    analytics_cache_get,
    analytics_cache_set,
    build_cache_key,
)
from app.analytics.capabilities import AnalyticsCapability
from app.analytics.periods import resolve_period
from app.analytics.scope import Scope, ScopeKind

WARSAW = ZoneInfo("Europe/Warsaw")

_PERIOD = resolve_period("month", now=datetime(2026, 7, 16, 12, tzinfo=WARSAW))
_ORG = Scope(kind=ScopeKind.organization)

_VIEWER_CAPS = frozenset({AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES})
_FINANCE_CAPS = frozenset(
    {
        AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
        AnalyticsCapability.VIEW_FINANCE,
    }
)


def _key(**overrides) -> str:
    params = dict(
        capabilities=_VIEWER_CAPS,
        scope=_ORG,
        period=_PERIOD,
        filters=None,
    )
    # Nierealny endpoint: cache jest module-global i przeżywa między plikami
    # testów — użycie 'overview' zatruwałoby wpisy dla testów API v1.
    endpoint = overrides.pop("endpoint", "cache-isolation-test")
    params.update(overrides)
    return build_cache_key(endpoint, **params)


def test_key_is_deterministic():
    assert _key() == _key()


def test_key_differs_by_capability_set():
    """Viewer-safe i finance NIGDY nie współdzielą wpisu cache."""
    assert _key(capabilities=_VIEWER_CAPS) != _key(capabilities=_FINANCE_CAPS)


def test_key_differs_by_endpoint():
    assert _key(endpoint="cache-isolation-test") != _key(endpoint="other-endpoint")


def test_key_differs_by_scope():
    org = _key(scope=Scope(kind=ScopeKind.organization))
    client_1 = _key(scope=Scope(kind=ScopeKind.client, client_id=1))
    client_2 = _key(scope=Scope(kind=ScopeKind.client, client_id=2))
    user_5 = _key(scope=Scope(kind=ScopeKind.user, user_id=5))
    assert len({org, client_1, client_2, user_5}) == 4


def test_key_differs_by_period():
    p_day = resolve_period("day", now=datetime(2026, 7, 16, 12, tzinfo=WARSAW))
    p_custom = resolve_period(
        "custom", date_from=date(2026, 7, 1), date_to=date(2026, 7, 31)
    )
    keys = {_key(period=_PERIOD), _key(period=p_day), _key(period=p_custom)}
    assert len(keys) == 3


def test_key_differs_by_filters():
    assert _key(filters={"team": 1}) != _key(filters={"team": 2})
    assert _key(filters=None) != _key(filters={"team": 1})
    # Kanoniczna serializacja: kolejność kluczy filtrów bez znaczenia.
    assert _key(filters={"a": 1, "b": 2}) == _key(filters={"b": 2, "a": 1})


def test_key_differs_by_metric_version():
    assert _key() != _key(metric_version=METRIC_VERSION + ".next")


def test_key_has_analytics_prefix():
    assert _key().startswith("analytics:v1:cache-isolation-test:")


@pytest.mark.asyncio
async def test_cache_roundtrip_and_isolation():
    key_viewer = _key(capabilities=_VIEWER_CAPS)
    key_finance = _key(capabilities=_FINANCE_CAPS)

    await analytics_cache_set(key_viewer, {"who": "viewer"}, ttl_seconds=30)
    await analytics_cache_set(key_finance, {"who": "finance"}, ttl_seconds=30)

    assert await analytics_cache_get(key_viewer) == {"who": "viewer"}
    assert await analytics_cache_get(key_finance) == {"who": "finance"}


@pytest.mark.asyncio
async def test_cache_helpers_reject_foreign_keys():
    with pytest.raises(ValueError):
        await analytics_cache_get("dashboard:kpis")
    with pytest.raises(ValueError):
        await analytics_cache_set("dashboard:kpis", {}, ttl_seconds=10)
