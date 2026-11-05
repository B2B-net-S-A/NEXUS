"""Gwarancja premii DL (05.11.2026): termin i rozdział potrąceń — bez bazy.

Konsultant musi być na kontrakcie do dnia przed rocznicą startu; dług
potrąca się z premii osoby najwyżej do ich sumy, od najstarszego, w walucie
długu. Ścieżki z bazą (automat, zamknięcie miesiąca, API) są w
``test_hr_bonus_guarantee_api.py``. Dane fikcyjne.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Optional

from app.models.contract import Contract, ContractStatus
from app.services.hr.bonus_guarantee import (
    _Debt,
    allocate,
    check_contract,
    deducted_by_currency,
    guarantee_until,
)

TODAY = date(2026, 11, 5)


def _contract(
    start: Optional[date],
    *,
    end: Optional[date] = None,
    status: ContractStatus = ContractStatus.ended,
    terminated: Optional[date] = None,
) -> Contract:
    return Contract(
        start_date=start, end_date=end, status=status, terminated_at=terminated
    )


# ── Termin ───────────────────────────────────────────────────────────────────


def test_guarantee_lasts_until_day_before_anniversary() -> None:
    assert guarantee_until(date(2026, 11, 3)) == date(2027, 11, 2)


def test_leap_day_start_ends_on_last_day_of_february() -> None:
    assert guarantee_until(date(2028, 2, 29)) == date(2029, 2, 28)


def test_end_before_anniversary_breaks_guarantee() -> None:
    check = check_contract(_contract(date(2026, 11, 3), end=date(2026, 11, 4)), TODAY)
    assert check.broken and check.ended_on == date(2026, 11, 4)


def test_end_on_last_guaranteed_day_keeps_guarantee() -> None:
    contract = _contract(date(2025, 11, 3), end=date(2026, 11, 2))
    assert not check_contract(contract, TODAY).broken


def test_planned_end_in_future_is_not_a_departure_yet() -> None:
    contract = _contract(
        date(2026, 6, 1), end=date(2026, 12, 31), status=ContractStatus.ending
    )
    assert not check_contract(contract, TODAY).broken


def test_active_contract_ignores_termination_trace_after_restore() -> None:
    contract = _contract(
        date(2026, 6, 1), status=ContractStatus.active, terminated=date(2026, 9, 1)
    )
    assert not check_contract(contract, TODAY).broken


def test_ended_without_date_inside_guarantee_breaks_it() -> None:
    check = check_contract(_contract(date(2026, 6, 1)), TODAY)
    assert check.broken and check.ended_on is None


def test_ended_without_date_after_guarantee_keeps_it() -> None:
    assert not check_contract(_contract(date(2024, 6, 1)), TODAY).broken


def test_contract_without_start_has_no_guarantee() -> None:
    assert not check_contract(_contract(None, end=date(2026, 10, 1)), TODAY).broken


# ── Rozdział potrąceń ────────────────────────────────────────────────────────


def _debt(clawback_id: int, remaining: str, currency: str = "PLN") -> _Debt:
    return _Debt(clawback_id, 1, currency, Decimal(remaining))


def test_debt_bigger_than_bonus_takes_whole_bonus_and_carries_rest() -> None:
    debt = _debt(1, "1512.00")
    first = allocate([debt], {"PLN": Decimal("1000.00")})
    assert [(d.clawback_id, d.amount) for d in first] == [(1, Decimal("1000.00"))]
    assert debt.remaining == Decimal("512.00")
    second = allocate([debt], {"PLN": Decimal("800.00")})
    assert [d.amount for d in second] == [Decimal("512.00")]
    assert debt.remaining == 0


def test_several_debts_go_oldest_first() -> None:
    older, newer = _debt(1, "300.00"), _debt(2, "500.00")
    taken = allocate([older, newer], {"PLN": Decimal("600.00")})
    assert [(d.clawback_id, d.amount) for d in taken] == [
        (1, Decimal("300.00")),
        (2, Decimal("300.00")),
    ]
    assert newer.remaining == Decimal("200.00")


def test_debt_only_takes_bonuses_in_its_currency() -> None:
    debt = _debt(1, "100.00", "EUR")
    assert allocate([debt], {"PLN": Decimal("5000.00")}) == []
    assert debt.remaining == Decimal("100.00")


def test_month_without_bonuses_deducts_nothing() -> None:
    assert allocate([_debt(1, "10.00")], {}) == []


def test_deductions_sum_per_currency() -> None:
    taken = allocate(
        [_debt(1, "100.00"), _debt(2, "50.00"), _debt(3, "20.00", "EUR")],
        {"PLN": Decimal("120.00"), "EUR": Decimal("20.00")},
    )
    assert deducted_by_currency(taken) == {
        "PLN": Decimal("120.00"),
        "EUR": Decimal("20.00"),
    }
