"""Runda 10 audytu — pieniądze (MONEY): testy bez bazy.

* R10-N9-1 — ``fold_money`` liczy kontrakty bez stawki przychodowej.
* R10-N9-3 — ``running_on`` na dziś wymaga statusu active/ending.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from app.core.scheduling import business_today
from app.models.contract import Contract, ContractStatus, RateUnit
from app.services.insights_board_money import fold_money, running_on


def _contract(**overrides) -> Contract:
    fields = dict(
        status=ContractStatus.active,
        start_date=date(2025, 1, 1),
        end_date=None,
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=168,
        rate_client=Decimal("150"),
        rate_candidate=Decimal("120"),
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
    )
    fields.update(overrides)
    return Contract(**fields)


# ── R10-N9-1 ────────────────────────────────────────────────────────────────


def test_contract_without_revenue_leg_is_counted_not_silently_dropped():
    contract = _contract(rate_client=None)

    fold = fold_money([contract], business_today(), {"PLN": Decimal("1")})

    assert fold.without_revenue_leg == 1
    assert fold.revenue == 0 and fold.cost == 0 and fold.margin == 0
    # ``complete`` mówi o kursach (steruje remisem wyścigu) — bez zmian.
    assert fold.complete is True


def test_priced_contract_does_not_count_as_missing_revenue_leg():
    fold = fold_money([_contract()], business_today(), {"PLN": Decimal("1")})

    assert fold.without_revenue_leg == 0
    assert fold.revenue == Decimal(150 * 168)


# ── R10-N9-3 ────────────────────────────────────────────────────────────────


def test_ended_contract_without_end_date_is_not_running_today():
    today = business_today()
    ended = _contract(status=ContractStatus.ended, end_date=None)
    ended_future = _contract(
        status=ContractStatus.ended, end_date=today + timedelta(days=30)
    )
    active = _contract()
    ending = _contract(status=ContractStatus.ending, end_date=today + timedelta(days=5))

    running = running_on([ended, ended_future, active, ending], today)

    assert ended not in running
    assert ended_future not in running
    assert active in running and ending in running


def test_past_day_still_decided_by_dates_only():
    """Dla dnia z przeszłości status mówi o dziś, nie o tamtym dniu."""
    ended = _contract(status=ContractStatus.ended, end_date=date(2025, 6, 30))

    assert ended in running_on([ended], date(2025, 3, 1))
    assert ended not in running_on([ended], date(2025, 7, 1))


# ── R10-X1-1 ────────────────────────────────────────────────────────────────


def _invoice_payload(**overrides) -> dict:
    payload = {
        "contract_id": 1,
        "direction": "to_client",
        "invoice_number": "R10/1",
        "issue_date": date(2026, 9, 1),
        "amount": "12345.67",
    }
    payload.update(overrides)
    return payload


def test_invoice_amount_keeps_grosze():
    from app.api.invoices import InvoiceCreate, InvoiceUpdate

    assert InvoiceCreate(**_invoice_payload()).amount == Decimal("12345.67")
    assert InvoiceUpdate(amount=12345.67).amount == Decimal("12345.67")


def test_invoice_amount_rejects_zero_and_fractions_of_grosz():
    import pytest
    from pydantic import ValidationError

    from app.api.invoices import InvoiceCreate, InvoiceUpdate

    for bad in ("0", "0.00", "1.234"):
        with pytest.raises(ValidationError):
            InvoiceCreate(**_invoice_payload(amount=bad))
    with pytest.raises(ValidationError):
        InvoiceUpdate(amount=0)


def test_invoice_response_amount_is_a_json_number():
    from app.api.invoices import InvoiceResponse

    body = InvoiceResponse(
        id=1, **_invoice_payload(amount=Decimal("12345.67"))
    ).model_dump(mode="json")
    assert body["amount"] == 12345.67


def test_invoice_amount_column_is_numeric_with_grosze():
    from app.models.invoice import Invoice

    column_type = Invoice.__table__.c.amount.type
    assert (column_type.precision, column_type.scale) == (14, 2)


def test_invoice_amount_migration_is_mirrored_in_entrypoint():
    from pathlib import Path

    # Moduł migracji zaczyna się cyfrą — czytamy stałą z pliku wprost.
    backend = Path(__file__).resolve().parents[1]
    source = (
        backend / "alembic" / "versions" / "0391_money_invoice_amount_grosze.py"
    ).read_text()
    namespace: dict = {}
    start = source.index("WIDEN_INVOICE_AMOUNT = ")
    end = source.index('END $$"""', start) + len('END $$"""')
    exec(source[start:end], namespace)
    ddl = namespace["WIDEN_INVOICE_AMOUNT"]
    assert ddl in (backend / "entrypoint.sh").read_text()
