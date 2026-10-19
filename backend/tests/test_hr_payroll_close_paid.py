"""Ponowne zamknięcie miesiąca po opłaconym rozliczeniu (audyt 19.10.2026).

Decyzja Artura: zmiana kwoty osoby, której rozliczenie miesiąca jest już
opłacone, blokuje zamknięcie (409 ``paid_settlement_changed``) — różnica nie
miałaby przelewu. Czyste porównanie bez bazy; ścieżka API w
``test_hr_settlements_api.py``. Dane fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

from app.services.hr.payroll_close import paid_settlement_changes
from app.services.hr.payroll_report import CurrencyLine, PersonPayroll


def _person(user_id: int, *totals: tuple[str, str]) -> PersonPayroll:
    return PersonPayroll(
        user_id=user_id,
        name=f"Osoba {user_id}",
        employment_type="zlecenie",
        manager_user_id=None,
        timesheet_required=True,
        timesheet_status="approved",
        hours=Decimal("10"),
        overtime_hours=Decimal("0"),
        paid_leave_days=Decimal("0"),
        other_leave_days=Decimal("0"),
        rate_missing=False,
        lines=tuple(
            CurrencyLine(
                currency=currency,
                hourly_rate=None,
                hours_amount=None,
                bonus_total=Decimal("0"),
                total=Decimal(total),
            )
            for currency, total in totals
        ),
    )


def test_same_amount_as_paid_settlement_closes() -> None:
    people = [_person(1, ("PLN", "1000.00"))]
    assert paid_settlement_changes(people, {(1, "PLN"): Decimal("1000.00")}) == []


def test_added_bonus_after_payment_is_a_change() -> None:
    people = [_person(1, ("PLN", "1500.00")), _person(2, ("PLN", "700.00"))]
    changed = paid_settlement_changes(people, {(1, "PLN"): Decimal("1000.00")})
    assert changed == [{"user_id": 1, "name": "Osoba 1", "currency": "PLN"}]


def test_line_gone_after_reopen_is_a_change() -> None:
    changed = paid_settlement_changes([], {(3, "EUR"): Decimal("50.00")})
    assert changed == [{"user_id": 3, "name": None, "currency": "EUR"}]


def test_people_without_paid_settlement_are_not_checked() -> None:
    assert paid_settlement_changes([_person(4, ("PLN", "10.00"))], {}) == []


# ── Premia przyznana, a kontrakt skończył się przed terminem ────────────────


def test_no_ended_early_bonuses_means_no_warning() -> None:
    from app.services.hr.payroll_close import ended_early_warning

    assert ended_early_warning([]) is None


def test_ended_early_warning_counts_bonuses_without_amounts() -> None:
    from app.services.hr.payroll_close import ended_early_warning

    warning = ended_early_warning([{"bonus_id": 7, "user_id": 1, "name": "Osoba 1"}])
    assert warning is not None
    assert warning["code"] == "bonus_contract_ended_early"
    assert warning["count"] == 1
    assert "przepada" in warning["message"]
