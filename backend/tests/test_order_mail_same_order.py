"""Dokument z maila powtarzający zapisane zamówienie (28.11.2026) — reguła bez bazy.

Część na bazie (ponowna weryfikacja zamyka taki dokument) jest w
``test_order_mail_same_order_db.py``. Osoby, numery i stawki są zmyślone.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.services.order_mail_same_order import (
    FIELD_CURRENCY,
    FIELD_PERIOD,
    FIELD_POOL,
    FIELD_RATE,
    OrderSnapshot,
    check_rows,
    differs_from_order_reason,
    row_differences,
    same_as_order_reason,
)


def _order(**fields) -> OrderSnapshot:
    base = dict(
        id=501,
        numbers=("7001/2033",),
        start_date=date(2033, 3, 1),
        end_date=date(2033, 3, 31),
        rate_client=Decimal("150.000"),
        rate_unit="hourly",
        billing_hours_per_month=168,
        currency="PLN",
        md_total=None,
        total_value=None,
    )
    base.update(fields)
    return OrderSnapshot(**base)


def _row(**fields) -> dict:
    base = dict(
        row_index=0,
        row_name="Jan Testowy",
        action="revision",
        contract_id=11,
        title="7001/2033",
        start_date="2033-03-01",
        end_date="2033-03-31",
        rate_client="1200.0",
        rate_unit="day",
        md_total="21",
        total_value="25200.0",
        currency="PLN",
    )
    base.update(fields)
    return base


def _proposal(*rows, blocking=()) -> dict:
    return {
        "order_number": "7001/2033",
        "rows": list(rows),
        "blocking": list(blocking),
    }


def test_same_number_period_and_rate_in_another_unit_is_the_same_order():
    # 1200 zł/MD w PDF-ie to 150 zł/h w zamówieniu (1 MD = 8 h). Zamówienie
    # założone ręcznie nie ma puli — dokument jej nie przeczy.
    check = check_rows(_proposal(_row()), {11: [_order()]})
    assert check.closes
    assert check.same_order_ids == [501]
    assert check.differences == []


def test_a_misread_rate_keeps_the_document_and_names_the_field():
    check = check_rows(_proposal(_row(rate_client="18700.0")), {11: [_order()]})
    assert not check.closes
    assert check.differences == [("Jan Testowy", 501, [FIELD_RATE])]
    assert (
        differs_from_order_reason(*check.differences[0])
        == "„Jan Testowy”: odczyt różni się od #501: stawka"
    )


def test_rate_within_a_grosz_after_conversion_is_the_same():
    # 1001,55 zł/MD zapisane jako 125,194 zł/h (zaokrąglenie do 0,001).
    order = _order(rate_client=Decimal("125.194"))
    assert row_differences(_row(rate_client="1001.55", total_value=None), order) == []
    assert row_differences(_row(rate_client="1001.60", total_value=None), order) == [
        FIELD_RATE
    ]


def test_a_different_period_keeps_the_document():
    row = _row(end_date="2033-04-30")
    assert row_differences(row, _order()) == [FIELD_PERIOD]


def test_a_different_pool_keeps_the_document_when_both_sides_have_one():
    order = _order(md_total=Decimal("21"), total_value=Decimal("25200"))
    assert row_differences(_row(), order) == []
    assert row_differences(_row(md_total="18"), order) == [FIELD_POOL]
    assert row_differences(_row(total_value="25200.02"), order) == [FIELD_POOL]
    assert row_differences(_row(total_value="25200.01"), order) == []


def test_a_foreign_currency_is_a_difference():
    assert row_differences(_row(currency="EUR"), _order()) == [FIELD_CURRENCY]


def test_a_row_without_rate_or_unit_is_never_the_same():
    assert FIELD_RATE in row_differences(_row(rate_client=None), _order())
    assert FIELD_RATE in row_differences(_row(rate_unit=None), _order())


def test_md_line_matches_by_the_group_number_and_its_pool():
    # Linia zamówienia MD: tytuł linii ma nazwisko, numer siedzi na grupie,
    # a wartość puli to MD × stawka linii.
    line = _order(
        id=777,
        numbers=("Zamówienie SAP 4509990001 — Jan Testowy", "SAP 4509990001"),
        start_date=date(2033, 3, 1),
        end_date=None,
        rate_client=Decimal("1600.000"),
        rate_unit="daily",
        md_total=Decimal("50"),
        total_value=Decimal("80000"),
    )
    row = _row(
        action="group",
        title="SAP 4509990001",
        end_date=None,
        rate_client="1600.00",
        md_total=None,
        total_value="80000",
    )
    check = check_rows(_proposal(row), {11: [line]})
    assert check.same_order_ids == [777]


def test_every_row_must_be_the_same():
    other = _row(row_index=1, row_name="Ewa Druga", contract_id=12, rate_client="900")
    orders = {11: [_order()], 12: [_order(id=502)]}
    check = check_rows(_proposal(_row(), other), orders)
    assert not check.closes
    assert check.differences == [("Ewa Druga", 502, [FIELD_RATE])]


def test_no_single_order_to_compare_with_leaves_the_document_alone():
    # Brak zamówienia o tym numerze, dwa zamówienia o tym numerze, brak
    # kontraktu i plan z blokadą — nic do zamknięcia i nic do dopisania.
    assert check_rows(_proposal(_row()), {11: [_order(numbers=("7002/2033",))]}) == (
        check_rows(_proposal(_row()), {})
    )
    twice = check_rows(_proposal(_row()), {11: [_order(), _order(id=503)]})
    assert not twice.closes and twice.differences == []
    assert not check_rows(_proposal(_row(contract_id=None)), {11: [_order()]}).closes
    blocked = check_rows(_proposal(_row(), blocking=["Brak numeru"]), {11: [_order()]})
    assert not blocked.closes and blocked.differences == []
    assert not check_rows(_proposal(), {11: [_order()]}).closes


def test_the_close_reason_names_the_order():
    assert same_as_order_reason([501]).startswith("To samo co zamówienie #501")
