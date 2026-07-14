"""Rollout module gating and cache-isolation tests for analytics v1."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.analytics.cache import (
    analytics_cache_get,
    analytics_cache_key,
    analytics_cache_set,
    invalidate_analytics_cache,
)
from app.analytics.periods import AnalyticsPeriodKind, WARSAW, resolve_period
from app.analytics.schemas import CallsData, METRIC_VERSION
from app.api.analytics_v1 import require_enabled_analytics_module
from app.core.config import settings
from app.models.user import UserRole


@dataclass
class _User:
    role: UserRole
    roles: list[str]

    def get_all_roles(self) -> set[UserRole]:
        return {self.role, *(UserRole(value) for value in self.roles)}


def _request(path: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": path,
            "headers": [],
        }
    )


def _period():
    return resolve_period(
        AnalyticsPeriodKind.month,
        now=datetime(2026, 7, 14, 12, tzinfo=WARSAW),
    )


@pytest.mark.asyncio
async def test_module_guard_is_fail_closed_but_control_plane_stays_available(
    monkeypatch,
) -> None:
    monkeypatch.setattr(settings, "ANALYTICS_V1_MODULES", "overview,funnel")

    await require_enabled_analytics_module(
        _request("/api/analytics/v1/overview")
    )
    await require_enabled_analytics_module(
        _request("/api/analytics/v1/recruitment/funnel")
    )
    await require_enabled_analytics_module(
        _request("/api/analytics/v1/meta/metrics")
    )
    await require_enabled_analytics_module(
        _request("/api/analytics/v1/admin/cutovers/finance")
    )

    with pytest.raises(HTTPException) as exc:
        await require_enabled_analytics_module(
            _request("/api/analytics/v1/finance/summary")
        )
    assert exc.value.status_code == 503


def test_default_module_list_covers_every_live_surface() -> None:
    enabled = {
        value.strip() for value in settings.ANALYTICS_V1_MODULES.split(",")
    }

    assert {
        "overview",
        "pipeline",
        "funnel",
        "recruitment",
        "sources",
        "calls",
        "kpis",
        "clients",
        "finance",
        "tenders",
        "delivery",
        "executive",
    } <= enabled


def test_cache_key_isolated_by_capability_scope_period_and_params() -> None:
    viewer = _User(UserRole.user, [UserRole.user.value])
    recruiter = _User(UserRole.recruiter, [UserRole.recruiter.value])
    period = _period()
    base = analytics_cache_key(
        "overview",
        user=viewer,
        scope="organization_redacted",
        period=period,
        params={"limit": 10},
    )

    assert METRIC_VERSION in base
    assert "view_operational_aggregates" in base
    assert base != analytics_cache_key(
        "overview",
        user=recruiter,
        scope="organization_redacted",
        period=period,
        params={"limit": 10},
    )
    assert base != analytics_cache_key(
        "overview",
        user=viewer,
        scope="client:7",
        period=period,
        params={"limit": 10},
    )
    assert base != analytics_cache_key(
        "overview",
        user=viewer,
        scope="organization_redacted",
        period=resolve_period(
            AnalyticsPeriodKind.day,
            now=datetime(2026, 7, 14, 12, tzinfo=WARSAW),
        ),
        params={"limit": 10},
    )
    assert base != analytics_cache_key(
        "overview",
        user=viewer,
        scope="organization_redacted",
        period=period,
        params={"limit": 20},
    )


@pytest.mark.asyncio
async def test_typed_cache_round_trip_uses_pydantic_contract() -> None:
    key = analytics_cache_key(
        "calls.test",
        user=_User(UserRole.user, [UserRole.user.value]),
        scope="test",
        period=_period(),
    )
    expected = CallsData(
        completed=3,
        inbound=1,
        outbound=2,
        total_duration_seconds=90,
        average_duration_seconds=30.0,
    )

    await analytics_cache_set(key, expected, ttl_seconds=30)
    restored = await analytics_cache_get(key, CallsData)
    await invalidate_analytics_cache()

    assert restored == expected
