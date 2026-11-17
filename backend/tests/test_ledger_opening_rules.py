"""Bilans otwarcia z Symfonii (K2) — odczyt pliku bez bazy.

Kwoty w zapisie polskim i z Excela, nagłówki BO / Saldo / Wn-Ma / jedno saldo,
odmowa przy kolumnach i BO, i salda końcowego, pomijanie sum i zer, scalanie
tego samego konta, CSV w cp1250. Konta i kwoty fikcyjne.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.services.finance_ledger.counterparty_import import ImportFileError
from app.services.ledger import opening


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1 234,56", Decimal("1234.56")),
        ("1234.56", Decimal("1234.56")),
        ("1.234,56", Decimal("1234.56")),
        ("1,234.56", Decimal("1234.56")),
        ("-1 234,56", Decimal("-1234.56")),
        ("(1 234,56)", Decimal("-1234.56")),
        ("1234.5600000000002", Decimal("1234.56")),
        ("", Decimal("0")),
        ("12 345", Decimal("12345")),
    ],
)
def test_amounts_in_polish_and_excel_notation(raw, expected):
    assert opening.parse_amount(raw) == expected


@pytest.mark.parametrize("raw", ["abc", "1,234,5", "12.345", "1e400", "0.001"])
def test_unreadable_amounts_are_refused(raw):
    assert opening.parse_amount(raw) is None


def _csv(text: str, encoding: str = "utf-8") -> bytes:
    return text.encode(encoding)


def test_opening_columns_net_debit_and_credit_and_skip_totals_and_zeros():
    parsed = opening.parse(
        _csv(
            "Zestawienie obrotów i sald\n"
            "Konto;Nazwa;BO Wn;BO Ma;Obroty Wn;Obroty Ma\n"
            "131-1;Rachunek;10 000,00;;5,00;5,00\n"
            "201-2-1042;Dostawca;100,00;350,00;;\n"
            "201-2-1042;Dostawca;;50,00;;\n"
            "800;Kapitał;;9 700,00;;\n"
            "202;Zero;0,00;0,00;;\n"
            "Razem;;10 100,00;10 100,00;;\n"
        )
    )
    assert {row.account: row.amount for row in parsed.rows} == {
        "131-1": 1_000_000,
        "201-2-1042": -30_000,
        "800": -970_000,
    }
    assert parsed.skipped == 2 and parsed.errors == []


def test_single_balance_column_with_sign():
    parsed = opening.parse(_csv("Konto,Saldo\n131,500.00\n800,-500.00\n"))
    assert [(row.account, row.amount) for row in parsed.rows] == [
        ("131", 50_000),
        ("800", -50_000),
    ]


def test_closing_balance_columns_of_previous_year():
    parsed = opening.parse(
        _csv(
            "Konto\tNazwa\tSaldo końcowe Wn\tSaldo końcowe Ma\n131\tKasa\t20,00\t\n800\tKapitał\t\t20,00\n"
        )
    )
    assert sum(row.amount for row in parsed.rows) == 0


ZOIS = (
    "Zestawienie obrotów i sald\n"
    "Konto;Nazwa;BO Wn;BO Ma;Obroty Wn;Obroty Ma;Saldo Wn;Saldo Ma\n"
    "010;Środki trwałe;1 000,00;;50,00;;1 050,00;\n"
    "010-1;ŚT grunty;400,00;;50,00;;450,00;\n"
    "010-2;ŚT budynki;600,00;;;;600,00;\n"
    "201;Dostawcy;;300,00;;;;300,00\n"
    "201-2;Dostawcy krajowi;;300,00;;;;300,00\n"
    "201-2-7;Dostawca A;;100,00;;;;100,00\n"
    "201-2-9;Dostawca B;;200,00;;;;200,00\n"
    "800;Kapitał;;700,00;;;;750,00\n"
    "Razem;;1 000,00;1 000,00;;;;\n"
)


def test_file_with_opening_and_closing_columns_opens_the_year_with_opening():
    parsed = opening.parse(_csv(ZOIS))
    assert (parsed.basis, parsed.both_bases) == ("bo", True)
    assert {row.account: row.amount for row in parsed.rows} == {
        "010-1": 40_000,
        "010-2": 60_000,
        "201-2-7": -10_000,
        "201-2-9": -20_000,
        "800": -70_000,
    }
    assert parsed.errors == []
    assert sum(row.amount for row in parsed.rows) == 0
    assert parsed.synthetic_skipped == 3  # 010, 201, 201-2


def test_closing_balance_can_be_chosen_explicitly():
    parsed = opening.parse(_csv(ZOIS), basis="saldo")
    assert parsed.basis == "saldo"
    amounts = {row.account: row.amount for row in parsed.rows}
    assert amounts["010-1"] == 45_000 and amounts["800"] == -75_000


def test_unknown_basis_is_refused():
    with pytest.raises(ImportFileError):
        opening.parse(_csv(ZOIS), basis="inne")


def test_synthetic_row_that_analytics_do_not_explain_is_an_error():
    parsed = opening.parse(
        _csv(
            "Konto;BO Wn;BO Ma\n"
            "131;500,00;\n"
            "131-1;200,00;\n"
            "131-2;100,00;\n"
            "800;;500,00\n"
        )
    )
    assert [error["line"] for error in parsed.errors] == [2]
    assert "131" in parsed.errors[0]["message"]


def test_synthetic_row_without_amount_on_analytics_stays():
    parsed = opening.parse(
        _csv("Konto;BO Wn;BO Ma\n131;500,00;\n131-1;;\n800;;500,00\n")
    )
    assert {row.account for row in parsed.rows} == {"131", "800"}
    assert parsed.synthetic_skipped == 0


def test_missing_header_is_refused():
    with pytest.raises(ImportFileError):
        opening.parse(_csv("A;B;C\n1;2;3\n"))


def test_cp1250_csv_and_row_errors():
    parsed = opening.parse(
        _csv("Konto;Nazwa;Wn;Ma\n131;Środki pieniężne;12,50;\n80?;Zły;1;\n", "cp1250")
    )
    assert parsed.rows[0].name == "Środki pieniężne"
    assert parsed.errors and parsed.errors[0]["line"] == 3


def test_file_without_any_balance_is_refused():
    with pytest.raises(ImportFileError):
        opening.parse(_csv("Konto;Wn;Ma\n131;0;0\n"))
