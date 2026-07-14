"""Focused manager/finance correctness tests for analytics v1."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from dataclasses import dataclass

import pytest

from app.analytics.periods import AnalyticsPeriodKind, WARSAW, resolve_period
from app.analytics.schemas import AnalyticsQualityStatus, FinancialAdjustmentCreate
from app.analytics.scope import require_client_scope
from app.models.user import UserRole
from app.services.analytics_v1.finance import (
    convert_currency_rows,
    money_string,
)
from app.services.analytics_v1.manager import (
    AnalyticsManagerService,
    _ADJUSTMENTS_SQL,
    _CLIENT_OPERATIONS_SQL,
    _TREND_ADJUSTMENTS_SQL,
    _report_date,
    _tender_outcome,
)


class _FakeResult:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def mappings(self) -> "_FakeResult":
        return self

    def all(self) -> list[dict]:
        return self.rows

    def one(self) -> dict:
        assert len(self.rows) == 1
        return self.rows[0]

    def one_or_none(self) -> dict | None:
        assert len(self.rows) <= 1
        return self.rows[0] if self.rows else None

    def scalar_one(self):
        assert len(self.rows) == 1
        return next(iter(self.rows[0].values()))


class _FakeSession:
    def __init__(self, result_sets: list[list[dict]]):
        self.result_sets = list(result_sets)
        self.calls: list[tuple[object, object]] = []

    async def execute(self, statement, params=None):
        self.calls.append((statement, params))
        assert self.result_sets, f"Unexpected query: {statement}"
        return _FakeResult(self.result_sets.pop(0))


@dataclass
class _ScopeUser:
    id: int
    role: UserRole

    def has_role(self, role: UserRole) -> bool:
        return self.role is role

    def has_any_role(self, *roles: UserRole) -> bool:
        return self.role in roles


class _ScopeDb:
    def __init__(self, value):
        self.value = value
        self.scalar_calls = 0

    async def scalar(self, _query):
        self.scalar_calls += 1
        return self.value


def _month_period():
    return resolve_period(
        AnalyticsPeriodKind.month,
        now=datetime(2026, 7, 14, 12, tzinfo=WARSAW),
    )


def test_decimal_money_serialization_never_uses_float() -> None:
    assert money_string(Decimal("123.456")) == "123.46"
    assert money_string(Decimal("0.10")) == "0.10"
    assert money_string(None) is None


def test_missing_fx_rate_invalidates_all_monetary_totals() -> None:
    value = convert_currency_rows(
        [
            {
                "currency": "EUR",
                "revenue": Decimal("100"),
                "costs": Decimal("60"),
                "active_contracts": 1,
                "incomplete_contracts": 0,
            }
        ],
        report_date=date(2026, 7, 14),
        history={},
    )

    assert value.quality_status is AnalyticsQualityStatus.unavailable
    assert value.revenue is None
    assert value.costs is None
    assert value.margin is None
    assert value.missing_currencies == ("EUR",)


def test_cached_historical_fx_is_applied_with_decimal_arithmetic() -> None:
    value = convert_currency_rows(
        [
            {
                "currency": "EUR",
                "revenue": Decimal("100.10"),
                "costs": Decimal("50.05"),
                "active_contracts": 1,
                "incomplete_contracts": 0,
            }
        ],
        report_date=date(2026, 7, 14),
        history={"EUR": ((date(2026, 7, 11), Decimal("4.25")),)},
    )

    assert value.revenue == Decimal("425.4250")
    assert value.costs == Decimal("212.7125")
    assert value.margin == Decimal("212.7125")


@pytest.mark.asyncio
async def test_finance_summary_suppresses_values_when_cache_has_no_rate() -> None:
    db = _FakeSession(
        [
            [
                {
                    "client_id": 7,
                    "client_name": "Client",
                    "currency": "EUR",
                    "active_contracts": 1,
                    "incomplete_contracts": 0,
                    "revenue": Decimal("100"),
                    "costs": Decimal("50"),
                }
            ],
            [],  # approved financial adjustments
            [],  # cached NBP rates: deliberately missing
        ]
    )

    result = await AnalyticsManagerService(db).finance_summary(  # type: ignore[arg-type]
        _month_period(),
        generated_at=datetime(2026, 7, 14, 12, tzinfo=WARSAW),
    )

    assert result.quality_status is AnalyticsQualityStatus.unavailable
    assert result.data.totals.revenue is None
    assert result.data.totals.costs is None
    assert result.data.totals.margin is None
    assert any("Missing NBP rate" in warning for warning in result.warnings)


@pytest.mark.asyncio
async def test_approved_adjustments_use_audited_amount_pln() -> None:
    db = _FakeSession(
        [
            [],  # no active contract finance
            [
                {
                    "currency": "PLN",
                    "active_contracts": 0,
                    "incomplete_contracts": 0,
                    "revenue": Decimal("0"),
                    "costs": Decimal("123.45"),
                }
            ],
        ]
    )

    result = await AnalyticsManagerService(db).finance_summary(  # type: ignore[arg-type]
        _month_period(),
        generated_at=datetime(2026, 7, 14, 12, tzinfo=WARSAW),
    )

    assert result.quality_status is AnalyticsQualityStatus.complete
    assert result.data.totals.costs == "123.45"
    assert result.data.totals.margin == "-123.45"
    assert "sum(amount_pln)" in str(_ADJUSTMENTS_SQL)
    assert "sum(amount_pln)" in str(_TREND_ADJUSTMENTS_SQL)
    assert "sum(amount)" not in str(_ADJUSTMENTS_SQL)


def test_client_operations_query_avoids_cross_product_aggregation() -> None:
    sql = str(_CLIENT_OPERATIONS_SQL)

    assert "GROUP BY cl.id" not in sql
    assert "LEFT JOIN jobs" not in sql
    assert "SELECT count(*)" in sql
    assert "hired.reached_at >= :period_start" in sql


@pytest.mark.asyncio
async def test_finance_trend_passes_calendar_dates_to_postgres() -> None:
    db = _FakeSession(
        [
            [
                {
                    "month_start": date(2026, 7, 1),
                    "currency": "PLN",
                    "active_contracts": 0,
                    "incomplete_contracts": 0,
                    "revenue": Decimal("0"),
                    "costs": Decimal("0"),
                }
            ],
            [],
        ]
    )

    await AnalyticsManagerService(db).finance_trend(  # type: ignore[arg-type]
        _month_period()
    )

    assert db.calls[0][1] == {
        "period_start": date(2026, 7, 1),
        "period_end": date(2026, 8, 1),
    }


@pytest.mark.asyncio
async def test_adjustment_approval_freezes_decimal_pln_value() -> None:
    now = datetime(2026, 7, 14, 12, tzinfo=WARSAW)
    current = {
        "id": 8,
        "adjustment_date": date(2026, 7, 14),
        "category": "other_cost",
        "description": "Audited cost",
        "amount": Decimal("1.005"),
        "currency": "PLN",
        "amount_pln": None,
        "fx_rate": None,
        "fx_date": None,
        "status": "draft",
        "created_by_user_id": 1,
        "approved_by_user_id": None,
        "approved_at": None,
        "created_at": now,
        "updated_at": now,
    }
    approved = {
        **current,
        "amount_pln": Decimal("1.01"),
        "fx_rate": Decimal("1"),
        "fx_date": date(2026, 7, 14),
        "status": "approved",
        "approved_by_user_id": 2,
        "approved_at": now,
    }
    db = _FakeSession([[current], [approved]])

    result = await AnalyticsManagerService(  # type: ignore[arg-type]
        db
    ).approve_financial_adjustment(8, approved_by_user_id=2)

    assert db.calls[1][1]["amount_pln"] == Decimal("1.01")
    assert result.amount_pln == "1.01"


def test_adjustment_input_normalizes_currency_and_rejects_zero() -> None:
    payload = FinancialAdjustmentCreate(
        adjustment_date=date(2026, 7, 14),
        category="  other_cost ",
        description=" Audited cost ",
        amount=Decimal("12.34"),
        currency="eur",
    )

    assert payload.currency == "EUR"
    assert payload.category == "other_cost"
    with pytest.raises(ValueError):
        FinancialAdjustmentCreate(
            adjustment_date=date(2026, 7, 14),
            category="other_cost",
            description="Audited cost",
            amount=Decimal("0"),
        )


def test_tender_outcome_uses_close_reason_not_priority() -> None:
    assert _tender_outcome("closed", "filled_by_us") == "won"
    assert _tender_outcome("closed", "budget") == "lost"
    assert _tender_outcome("closed", None) == "unknown"
    assert _tender_outcome("published", "filled_by_us") == "pending"


def test_finance_report_date_respects_half_open_period_end() -> None:
    period = resolve_period(
        AnalyticsPeriodKind.custom,
        date_from=date(2026, 1, 1),
        date_to=date(2026, 2, 1),
    )
    assert _report_date(
        period, datetime(2026, 7, 14, 12, tzinfo=WARSAW)
    ) == date(2026, 1, 31)


@pytest.mark.asyncio
async def test_delivery_lead_has_organization_wide_client_finance_scope() -> None:
    db = _ScopeDb(123)
    user = _ScopeUser(id=9, role=UserRole.delivery_lead)

    await require_client_scope(  # type: ignore[arg-type]
        db,
        user=user,  # type: ignore[arg-type]
        client_id=123,
        finance=True,
    )

    # One query verifies client existence; no assignment lookup is performed.
    assert db.scalar_calls == 1
