"""Focused unit/contract tests for the analytics v1 foundation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pytest
from fastapi import HTTPException

from app.analytics.capabilities import (
    AnalyticsCapability,
    analytics_capability_values,
    capabilities_for_user,
)
from app.analytics.periods import AnalyticsPeriodKind, WARSAW, resolve_period
from app.analytics.schemas import OverviewData
from app.models.user import UserRole
from app.services.analytics_v1 import AnalyticsV1Service
from app.services.analytics_v1.service import _kpi_targets, _record_target


@dataclass
class _TestUser:
    role: UserRole
    roles: list[str]

    def get_all_roles(self) -> set[UserRole]:
        out = {self.role}
        for role in self.roles:
            try:
                out.add(UserRole(role))
            except ValueError:
                continue
        return out


def _user(role: UserRole, *, roles: list[str] | None = None) -> _TestUser:
    return _TestUser(role=role, roles=roles or [role.value])


def test_viewer_receives_only_operational_aggregate_capability() -> None:
    user = _user(UserRole.user)

    assert capabilities_for_user(user) == frozenset(
        {AnalyticsCapability.view_operational_aggregates}
    )
    assert analytics_capability_values(user) == ["view_operational_aggregates"]


def test_multi_role_capabilities_are_a_union_but_hor_has_no_finance() -> None:
    hybrid = _user(
        UserRole.user,
        roles=[UserRole.user.value, UserRole.delivery_lead.value],
    )
    hor = _user(UserRole.head_of_recruitment)

    assert AnalyticsCapability.view_finance in capabilities_for_user(hybrid)
    assert AnalyticsCapability.view_personal_delivery_kpis in capabilities_for_user(
        hybrid
    )
    assert AnalyticsCapability.view_finance not in capabilities_for_user(hor)
    assert AnalyticsCapability.view_client_operations in capabilities_for_user(hor)


def test_only_admin_can_manage_financial_adjustments() -> None:
    admin = _user(UserRole.admin)
    delivery_lead = _user(UserRole.delivery_lead)

    assert AnalyticsCapability.manage_analytics in capabilities_for_user(admin)
    assert AnalyticsCapability.view_finance in capabilities_for_user(delivery_lead)
    assert AnalyticsCapability.manage_analytics not in capabilities_for_user(
        delivery_lead
    )


def test_day_period_uses_warsaw_calendar_across_dst_change() -> None:
    # 2026-03-29 is the 23-hour spring-forward day in Europe/Warsaw.
    now = datetime(2026, 3, 29, 12, 0, tzinfo=WARSAW)
    period = resolve_period(AnalyticsPeriodKind.day, now=now)

    assert period.start.isoformat() == "2026-03-29T00:00:00+01:00"
    assert period.end.isoformat() == "2026-03-30T00:00:00+02:00"
    assert (period.end.timestamp() - period.start.timestamp()) / 3600 == 23


def test_custom_period_is_half_open_and_limited_to_366_days() -> None:
    period = resolve_period(
        AnalyticsPeriodKind.custom,
        date_from=date(2024, 1, 1),
        date_to=date(2025, 1, 1),
    )

    assert period.start.date() == date(2024, 1, 1)
    assert period.end.date() == date(2025, 1, 1)

    with pytest.raises(HTTPException) as exc:
        resolve_period(
            AnalyticsPeriodKind.custom,
            date_from=date(2024, 1, 1),
            date_to=date(2025, 1, 2),
        )
    assert exc.value.status_code == 422


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def one(self) -> dict:
        assert len(self.rows) == 1
        return self.rows[0]

    def all(self) -> list[dict]:
        return self.rows


class _FakeSession:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.statement = None
        self.params = None

    async def execute(self, statement, params=None):
        self.statement = statement
        self.params = params
        return _FakeResult(self.rows)


@pytest.mark.asyncio
async def test_calls_use_completed_status_and_started_at_fallback() -> None:
    db = _FakeSession(
        [
            {
                "completed": 2,
                "inbound": 1,
                "outbound": 1,
                "total_duration_seconds": 180,
                "average_duration_seconds": 90,
            }
        ]
    )
    period = resolve_period(
        AnalyticsPeriodKind.month,
        now=datetime(2026, 7, 14, 12, 0, tzinfo=WARSAW),
    )

    data = await AnalyticsV1Service(db).calls(period, user_id=42)  # type: ignore[arg-type]

    sql = str(db.statement)
    assert "status = 'completed'" in sql
    assert "coalesce(started_at, created_at)" in sql
    assert "user_id = :user_id" in sql
    assert db.params["user_id"] == 42
    assert data.completed == 2


@pytest.mark.asyncio
async def test_sources_defensively_never_exceed_100_percent() -> None:
    db = _FakeSession(
        [
            {
                "source": "linkedin",
                "cohort_candidates": 2,
                "placed_by_period_end": 3,
            }
        ]
    )
    period = resolve_period(
        AnalyticsPeriodKind.month,
        now=datetime(2026, 7, 14, 12, 0, tzinfo=WARSAW),
    )

    data = await AnalyticsV1Service(db).sources(period)  # type: ignore[arg-type]

    assert data.sources[0].placed_by_period_end == 2
    assert data.sources[0].hire_rate_pct == 100.0


@pytest.mark.asyncio
async def test_overview_uses_report_date_not_period_start() -> None:
    db = _FakeSession(
        [
            {
                "candidates_total": 0,
                "candidates_active": 0,
                "jobs_total": 0,
                "jobs_open": 0,
                "clients_total": 0,
                "clients_active": 0,
                "contracts_active": 0,
                "contracts_expiring": 0,
                "contracts_incomplete_dates": 0,
                "placements": 0,
            }
        ]
    )
    period = resolve_period(
        AnalyticsPeriodKind.month,
        now=datetime(2026, 7, 14, 12, 0, tzinfo=WARSAW),
    )

    await AnalyticsV1Service(db).overview(  # type: ignore[arg-type]
        period,
        generated_at=datetime(2026, 7, 14, 12, 0, tzinfo=WARSAW),
    )

    assert db.params["report_date"] == date(2026, 7, 14)
    assert db.params["expiry_end"] == date(2026, 8, 14)
    sql = str(db.statement)
    assert "start_date IS NOT NULL" in sql
    assert "start_date <= :report_date" in sql


def test_viewer_safe_overview_schema_has_no_pii_or_financial_fields() -> None:
    fields = set(OverviewData.model_json_schema()["properties"])

    assert fields == {"candidates", "jobs", "clients", "contracts", "pipeline"}
    serialized_schema = str(OverviewData.model_json_schema()).lower()
    for forbidden in ("email", "name", "rate", "margin", "revenue", "profit"):
        assert forbidden not in serialized_schema


def test_kpi_targets_accept_legacy_ids_and_preserve_user_override_priority() -> None:
    candidates: dict[str, tuple[int, int, int]] = {}
    _record_target(
        candidates,
        raw_id="calls_daily",
        target_value=15,
        priority=2,
    )
    _record_target(
        candidates,
        raw_id="daily_activity_count",
        target_value=20,
        priority=1,
    )
    targets = _kpi_targets(
        "recruiter",
        {
            target_id: candidate[2]
            for target_id, candidate in candidates.items()
        },
    )
    legacy_targets = _kpi_targets(
        "recruiter",
        {
            "daily_verifications": 6,
            "daily_new_candidates": 7,
            "monthly_placements": 2,
        },
    )

    assert targets.calls_daily == 20
    assert legacy_targets.verifications_daily == 6
    assert legacy_targets.candidates_added_daily == 7
    assert legacy_targets.placements_monthly == 2
