"""Reguły kroków stawki przychodowej zamówienia — bez bazy.

Ticket Finansów 16.11.2026: aneks stawki klienta w kontrakcie nie zmieniał
zamówienia MD. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.models.contract import RateUnit
from app.services import order_revenue_steps as steps
from app.services import order_revenue_steps_schema as schema


def _contract(**over):
    base = dict(
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        resolved_rate_client_currency="PLN",
    )
    base.update(over)
    return SimpleNamespace(**base)


def _order(**over):
    base = dict(
        id=7,
        rate_unit=RateUnit.daily,
        rate_client=Decimal("1200.000"),
        md_rate_revenue=Decimal("1200.000"),
        rate_client_currency="PLN",
        currency="PLN",
        billing_hours_per_month=168,
    )
    base.update(over)
    return SimpleNamespace(**base)


def _step(day: date, rate: str, md: str | None = None):
    return SimpleNamespace(
        effective_from=day,
        rate_client=Decimal(rate),
        md_rate_revenue=Decimal(md) if md is not None else None,
    )


def test_first_priced_month_is_the_month_of_a_first_day_annex():
    assert steps.first_priced_month(date(2026, 11, 1)) == date(2026, 11, 1)


def test_mid_month_annex_is_priced_from_next_month():
    assert steps.first_priced_month(date(2026, 11, 15)) == date(2026, 12, 1)
    assert steps.first_priced_month(date(2026, 12, 31)) == date(2027, 1, 1)


def test_rates_before_first_step_come_from_the_order_columns():
    order = _order()
    own = [_step(date(2026, 11, 1), "1300.000", "1300.000")]
    assert steps.rates_on(order, own, date(2026, 10, 1)) == (
        Decimal("1200.000"),
        Decimal("1200.000"),
    )
    assert steps.rates_on(order, own, date(2026, 11, 1)) == (
        Decimal("1300.000"),
        Decimal("1300.000"),
    )


def test_latest_step_in_force_wins_regardless_of_list_order():
    order = _order()
    own = [
        _step(date(2027, 1, 1), "1400.000", "1400.000"),
        _step(date(2026, 11, 1), "1300.000", "1300.000"),
    ]
    assert steps.rates_on(order, own, date(2026, 12, 1))[1] == Decimal("1300.000")
    assert steps.rates_on(order, own, date(2027, 2, 1))[1] == Decimal("1400.000")


def test_md_order_gets_hourly_rate_times_eight_rounded_to_grosz():
    # 150,123 zł/h × 8 = 1200,984 → 1200,98 zł/MD: stawka MD jest kwotą
    # w groszach, trzecie miejsce to ślad przepisania stawki z ekranu.
    rate, md = steps.order_rates_from_contract(
        Decimal("150.123"), _contract(), _order()
    )
    assert rate == Decimal("1200.98")
    assert md == Decimal("1200.98")


def test_hourly_order_keeps_the_hourly_rate():
    order = _order(
        rate_unit=RateUnit.hourly, rate_client=Decimal("150"), md_rate_revenue=None
    )
    assert steps.order_rates_from_contract(Decimal("162.5"), _contract(), order) == (
        Decimal("162.500"),
        None,
    )


def test_other_currency_than_contract_is_left_alone():
    order = _order(rate_client_currency="EUR", currency="EUR")
    assert steps.order_rates_from_contract(Decimal("50"), _contract(), order) is None


def test_order_without_unit_is_left_alone():
    assert (
        steps.order_rates_from_contract(
            Decimal("50"), _contract(), _order(rate_unit=None)
        )
        is None
    )


def test_priced_order_reads_through_and_refuses_writes():
    order = _order(title="Zamówienie 9/2026")
    priced = steps.PricedOrder(order, Decimal("1300"), Decimal("1300"))
    assert priced.md_rate_revenue == Decimal("1300")
    assert priced.title == "Zamówienie 9/2026"
    assert order.md_rate_revenue == Decimal("1200.000")
    with pytest.raises(AttributeError):
        priced.md_rate_revenue = Decimal("1")


def test_backfill_window_is_closed_and_conflicts_keep_code_written_steps():
    sql = " ".join(schema.DATA_DDL)
    assert "a.effective_date >= DATE '2026-11-01'" in sql
    assert "a.created_at < TIMESTAMPTZ '2026-11-21" in sql
    assert "ON CONFLICT (order_id, effective_from) DO NOTHING" in sql
    # Ta sama reguła co kod: MD = stawka godzinowa × 8 do grosza.
    assert "round((a.new_values->>'rate_client')::numeric * 8, 2)" in sql
