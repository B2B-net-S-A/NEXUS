"""Paczka księgi do Symfonii (K3b) — reguły bez bazy: rodzaj dokumentu i plik."""

from __future__ import annotations

import csv
import io
from datetime import date
from decimal import Decimal

import pytest
from openpyxl import load_workbook

from app.services.finance_ledger.costs import LedgerError
from app.services.ledger import exports
from app.services.ledger.export_file import (
    COLUMNS,
    ExportLine,
    NeutralCsv,
    NeutralXlsx,
    money,
)


@pytest.mark.parametrize(
    ("doc_type", "source_type", "kind"),
    [
        ("PK", None, "manual"),
        ("BO", None, "opening"),
        ("BO", "opening_import", "opening"),
        ("FVZ", "finance_cost_entry", "costs"),
        ("FVS", "client_sales_invoice", "sales"),
        ("PK", "cost_allocation", "allocation"),
        ("PK", "ledger_recurring", "recurring"),
        ("PK", "ledger_prepayment", "prepayments"),
        ("PK", "something_new", "other"),
    ],
)
def test_kind_of_document(doc_type, source_type, kind):
    assert exports.kind_of(doc_type, source_type) == kind


def test_invoices_and_opening_stay_out_by_default():
    # Faktury mają własne drogi do Symfonii (E2, eBI24), BO przychodzi z Symfonii.
    assert exports.DEFAULT_KINDS == {"manual", "recurring", "prepayments", "allocation"}
    for kind in ("costs", "sales", "opening"):
        assert exports.KIND_NOTES[kind]


def test_chosen_kinds_refuses_empty_and_unknown():
    assert exports.chosen_kinds(["recurring", "recurring"]) == {"recurring"}
    with pytest.raises(LedgerError) as empty:
        exports.chosen_kinds([])
    assert empty.value.status == 422
    with pytest.raises(LedgerError) as unknown:
        exports.chosen_kinds(["recurring", "payroll_list"])
    assert unknown.value.status == 422 and "payroll_list" in unknown.value.message


def test_money_from_grosze():
    assert money(123_456) == Decimal("1234.56")
    assert money(1) == Decimal("0.01")
    assert money(None) is None


def _line(**changes) -> ExportLine:
    values = {
        "journal_no": 7,
        "number": "PK 3/03/2026",
        "doc_type": "PK",
        "doc_date": date(2026, 3, 31),
        "op_date": date(2026, 3, 31),
        "document_description": "Najem biura 03.2026",
        "line_no": 1,
        "account": "402-1",
        "debit": Decimal("1000.00"),
        "credit": None,
        "description": "Najem",
        "mpk": "OG",
        "counterparty": "Wynajmujący sp. z o.o.",
        "tax_id": "5260000000",
        "symfonia_id": "1042",
        "currency": "PLN",
        "amount_cur": None,
        "fx_rate": None,
        "fx_date": None,
        "reverses": None,
        "ksef_number": None,
    }
    values.update(changes)
    return ExportLine(**values)


def test_csv_has_header_bom_decimal_comma_and_no_formulas():
    lines = [
        _line(),
        _line(
            line_no=2,
            account="202-1042",
            debit=None,
            credit=Decimal("1000.00"),
            description="=HYPERLINK(\"http://x\")",
        ),
    ]
    content = NeutralCsv().render(lines)
    assert content.startswith("﻿".encode("utf-8"))
    rows = list(csv.reader(io.StringIO(content.decode("utf-8-sig")), delimiter=";"))
    assert rows[0] == [label for _, label in COLUMNS]
    header = rows[0]
    first = dict(zip(header, rows[1]))
    second = dict(zip(header, rows[2]))
    assert first["Wn"] == "1000,00" and first["Ma"] == ""
    assert first["Data operacji"] == "2026-03-31"
    assert second["Ma"] == "1000,00"
    # Tekst z danych nie staje się formułą w arkuszu.
    assert not second["Opis pozycji"].startswith("=")


def test_xlsx_rows_keep_numbers_dates_and_order():
    content = NeutralXlsx().render(
        [_line(), _line(line_no=2, debit=None, credit=Decimal("1000.00"))]
    )
    sheet = load_workbook(io.BytesIO(content)).active
    rows = list(sheet.iter_rows(values_only=True))
    assert list(rows[0]) == [label for _, label in COLUMNS]
    header = list(rows[0])
    first = dict(zip(header, rows[1]))
    second = dict(zip(header, rows[2]))
    assert first["Nr w dzienniku NEXUSA"] == 7
    assert first["Wn"] == 1000 and first["Ma"] is None
    assert second["Pozycja"] == 2 and second["Ma"] == 1000
    assert first["Data dokumentu"].date() == date(2026, 3, 31)
    assert first["ID Symfonii kontrahenta"] == "1042"
