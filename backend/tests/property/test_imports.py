"""Import invariants: localized numbers, column movement and order hints."""

from decimal import Decimal
from io import BytesIO

from hypothesis import given, settings, strategies as st
from openpyxl import Workbook

from app.services.md_import_parser import (
    extract_order_number_candidates,
    parse_md_sheet,
    parse_money_value,
)


@given(
    mills=st.integers(0, 100_000_000),
    separator=st.sampled_from([" ", "\u00a0"]),
    currency=st.sampled_from(["zł", "PLN", "zl", ""]),
)
def test_polish_money_preserves_precision(mills, separator, currency):
    amount = Decimal(mills) / 1000
    text = f"{amount:,.3f}".replace(",", separator).replace(".", ",")
    assert parse_money_value(f" {text} {currency} ") == amount


@given(numbers=st.lists(st.integers(100, 9_999_999_999), min_size=1, max_size=12))
def test_repeated_order_hints_are_unique_without_losing_candidates(numbers):
    text = " / ".join(f"SAP {number}" for number in numbers)
    hints = extract_order_number_candidates(text)
    assert set(hints) == {str(number) for number in numbers}
    assert len(hints) == len(set(hints))
    assert extract_order_number_candidates(text + " / " + text) == hints


@settings(max_examples=30, deadline=None)
@given(
    columns=st.permutations(
        ["Konsultant", "Średnia Stawka MD", "Ilość MD", "Faktura", "Uwagi"]
    ),
    md_mills=st.integers(0, 31_000),
    invoice_cents=st.integers(0, 5_000_000),
)
def test_moving_excel_columns_cannot_turn_a_rate_into_consumed_days(
    columns, md_mills, invoice_cents
):
    md, invoice = Decimal(md_mills) / 1000, Decimal(invoice_cents) / 100
    values = {
        "Konsultant": "Ewa Testowa",
        "Średnia Stawka MD": 1200,
        "Ilość MD": str(md).replace(".", ","),
        "Faktura": f"{invoice} PLN",
        "Uwagi": "SAP 4500810000",
    }
    workbook = Workbook()
    workbook.active.append(list(columns))
    workbook.active.append([values[column] for column in columns])
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    result = parse_md_sheet(stream.getvalue())
    assert result.skipped_rows == []
    assert len(result.rows) == 1
    row = result.rows[0]
    assert (row.md_reported, row.invoice_amount, row.order_number_hint) == (
        md,
        invoice,
        "4500810000",
    )
