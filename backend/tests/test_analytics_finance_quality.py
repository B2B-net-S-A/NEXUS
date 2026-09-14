"""Audyt statystyk 14.09.2026, A04: brak nogi kosztowej obniża jakość finansów.

``_sum_finance`` dodawało przychód, gdy była stawka klienta, a marżę tylko
w zagnieżdżonym ``if`` na stawkę kandydata. Kontrakt bez kosztu nie trafiał
do ``missing``, więc suma z marżą liczoną jak 0% wychodziła jako
``"complete"`` — bez jednego słowa o pominiętych kontraktach. Semantyka po
poprawce jest lustrem ``insights_board_money.MoneyFold.without_cost_leg``:
przychód wchodzi do MRR, marża NIE wchodzi jako zero, a wynik mówi, ile
kontraktów pominięto, i nosi flagę ``partial`` z ostrzeżeniem po polsku.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.analytics.metrics import _sum_finance
from app.core.database import AsyncSessionLocal
from app.models.contract import Contract, RateUnit

pytestmark = pytest.mark.asyncio


def _contract(rate_client: str | None, rate_candidate: str | None) -> Contract:
    """Nieprzypisana umowa PLN o miesięcznych stawkach (``None`` = brak nogi)."""
    return Contract(
        rate_client=Decimal(rate_client) if rate_client is not None else None,
        rate_candidate=Decimal(rate_candidate) if rate_candidate is not None else None,
        rate_unit=RateUnit.monthly,
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
    )


async def test_revenue_without_cost_leg_is_partial_not_complete():
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db, [_contract("10000", "7000"), _contract("5000", None)]
        )

    assert flag == "partial"
    # Przychód kontraktu bez kosztu WCHODZI do MRR (jak dotąd)...
    assert data["mrr"] == "15000.00"
    # ...ale jego marża nie wchodzi jako zero — zostaje tylko marża pełnego.
    assert data["monthly_margin"] == "3000.00"
    assert data["contracts_without_cost_leg"] == 1
    assert data["contracts_without_revenue_leg"] == 0
    assert any("bez stawki kandydata" in w for w in warnings), warnings


async def test_cost_without_revenue_leg_is_partial_and_counted():
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db, [_contract("10000", "7000"), _contract(None, "4000")]
        )

    assert flag == "partial"
    assert data["mrr"] == "10000.00"
    assert data["monthly_margin"] == "3000.00"
    assert data["contracts_without_cost_leg"] == 0
    assert data["contracts_without_revenue_leg"] == 1
    assert any("bez stawki klienta" in w for w in warnings), warnings


async def test_missing_fx_still_wins_over_partial():
    """``unavailable`` jest gorsze niż ``partial`` i nie może zostać
    przykryte przez brak nogi na innym kontrakcie."""
    foreign = _contract("1000", "100")
    foreign.rate_client_currency = "XXX"
    foreign.rate_candidate_currency = "XXX"
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(
            db, [foreign, _contract("5000", None)]
        )

    assert flag == "unavailable"
    assert data["contracts_without_cost_leg"] == 1
    assert any("Brak kursu" in w for w in warnings)
    assert any("Niepełna wycena" in w for w in warnings)


async def test_two_full_legs_stay_complete_with_zero_counters():
    async with AsyncSessionLocal() as db:
        data, warnings, flag = await _sum_finance(db, [_contract("10000", "7000")])

    assert flag == "complete"
    assert data["contracts_without_cost_leg"] == 0
    assert data["contracts_without_revenue_leg"] == 0
    assert not any("Niepełna wycena" in w for w in warnings)
