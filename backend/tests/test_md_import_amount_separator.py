"""Kwota faktury z jednym separatorem i trzema cyframi po nim (audyt 24.11.2026).

„12.500 zł” w polskim Excelu to dwanaście i pół tysiąca, a „1,234” w arkuszu
angielskim — tysiąc dwieście trzydzieści cztery. Parser brał oba jako ułamek
(12,5 i 1,234), faktura była 1000 razy za mała, a wiersz dostawał
„Rozliczono kwotowo”. Takiego zapisu nie da się rozstrzygnąć bez zgadywania:
wiersz zostaje z MD, faktura czeka na ręczne rozliczenie.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest

from app.services.md_import_parser import parse_md_sheet


def _book(rows: list[list]) -> bytes:
    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _row(invoice):
    parsed = parse_md_sheet(
        _book(
            [
                ["Konsultant", "MD", "Uwagi", "Faktura"],
                ["Osoba Testowa", 15, None, invoice],
            ]
        )
    )
    assert parsed.skipped_rows == []
    [row] = parsed.rows
    assert row.md_reported == Decimal("15")
    return row


@pytest.mark.parametrize("invoice", ["12.500 zł", "1,234", "-1.000", "12 .500 PLN"])
def test_single_separator_before_three_digits_is_ambiguous(invoice):
    row = _row(invoice)
    assert row.invoice_amount is None
    assert row.invoice_problem is not None
    assert row.invoice_problem.startswith("niejednoznaczny zapis kwoty")


@pytest.mark.parametrize(
    ("invoice", "expected"),
    [
        ("12.50", Decimal("12.50")),
        ("0,5", Decimal("0.5")),
        ("12.500,00 zł", Decimal("12500.00")),
        ("1,234.56", Decimal("1234.56")),
        ("12 500", Decimal("12500")),
        ("1234,567", Decimal("1234.567")),
        (12500, Decimal("12500")),
    ],
)
def test_unambiguous_amounts_are_read(invoice, expected):
    row = _row(invoice)
    assert row.invoice_problem is None
    assert row.invoice_amount == expected


def test_cost_only_row_with_ambiguous_amount_is_skipped_with_the_reason():
    parsed = parse_md_sheet(
        _book(
            [
                ["Konsultant", "MD", "Uwagi", "Faktura"],
                ["Osoba Testowa", None, "zamówienie ZAM/2026/01", "12.500 zł"],
            ]
        )
    )
    assert parsed.rows == []
    [skipped] = parsed.skipped_rows
    assert "niejednoznaczny zapis kwoty" in skipped["reason"]
