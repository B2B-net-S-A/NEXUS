"""Parser arkusza MD: kolumny „Uwagi" i „Faktura" + wyłuskanie numeru zamówienia.

Czysty parser — bez bazy i bez aplikacji.
"""

from __future__ import annotations

import io
from decimal import Decimal

from openpyxl import Workbook

from app.services.md_import_parser import (
    extract_order_number,
    extract_order_number_candidates,
    parse_md_sheet,
    parse_money_value,
)


def _sheet(headers: list[str], rows: list[list]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


# ── Numer zamówienia z „Uwag" ───────────────────────────────────────────────


def test_order_number_is_found_regardless_of_prefix():
    for text in ("SAP 4500719650", "4500719650", "zam. 4500719650 - II transza"):
        assert extract_order_number(text) == "4500719650"


def test_candidates_are_returned_for_confrontation_not_guessed():
    """Rok stoi w tej samej komórce co numer — wybór należy do warstwy, która
    widzi listę istniejących zamówień."""
    assert extract_order_number_candidates("SAP 4500719650 / 2026, II transza") == [
        "4500719650",
        "2026",
    ]


def test_short_order_numbers_are_recognised():
    # „Zamówienie nr 445" — u BIK numery bywają trzycyfrowe.
    assert extract_order_number("Zamówienie nr 445") == "445"


def test_no_digits_means_no_candidate():
    for text in ("brak", "", None, "urlop bezpłatny"):
        assert extract_order_number(text) is None


# ── Kwoty ───────────────────────────────────────────────────────────────────


def test_polish_money_formatting_is_understood():
    assert parse_money_value("20 900,00 zł") == Decimal("20900.00")
    assert parse_money_value("20 900,125 zł") == Decimal("20900.125")
    assert parse_money_value("1234.50") == Decimal("1234.50")
    assert parse_money_value("20\xa0900,00 PLN") == Decimal("20900.00")


def test_unreadable_money_is_none_not_zero():
    # Zero znaczyłoby „wystawiono zero", a nie „nie wiadomo".
    for text in ("b/d", "", None, "-"):
        assert parse_money_value(text) is None


# ── Arkusz ──────────────────────────────────────────────────────────────────


def test_sheet_without_the_new_columns_parses_exactly_as_before():
    """Arkusze sprzed rozliczeń kosztowych NIE mogą przestać się parsować."""
    parsed = parse_md_sheet(
        _sheet(["Imię i nazwisko", "Ilość MD"], [["Jan Kowalski", 15]])
    )
    assert parsed.notes_column is None
    assert parsed.invoice_column is None
    row = parsed.rows[0]
    assert row.consultant_name == "Jan Kowalski"
    assert row.md_reported == Decimal("15")
    assert row.notes_raw is None
    assert row.invoice_amount is None


def test_sheet_with_notes_and_invoice_carries_them_through():
    parsed = parse_md_sheet(
        _sheet(
            ["Imię i nazwisko", "Ilość MD", "Uwagi", "Faktura"],
            [["Jan Kowalski", 15, "SAP 4500719650", "20 900,00 zł"]],
        )
    )
    row = parsed.rows[0]
    assert row.notes_raw == "SAP 4500719650"
    assert row.order_number_hint == "4500719650"
    assert row.invoice_amount == Decimal("20900.00")


def test_extra_columns_do_not_shift_the_mapping():
    """Realny arkusz z Finansów ma 15 kolumn — mapowanie idzie po nagłówkach."""
    parsed = parse_md_sheet(
        _sheet(
            [
                "Imię i nazwisko",
                "Średnia Stawka MD",
                "Ilość MD",
                "Wynagrodzenie",
                "Klient",
                "Uwagi",
                "Projekt",
                "Faktura",
                "Marża PLN",
            ],
            [
                [
                    "Jan Kowalski",
                    1000,
                    15,
                    12000,
                    "Polkomtel",
                    "SAP 4500719650",
                    "Projekt X",
                    "20 900,00 zł",
                    3000,
                ]
            ],
        )
    )
    row = parsed.rows[0]
    assert row.md_reported == Decimal("15")
    assert row.order_number_hint == "4500719650"
    assert row.invoice_amount == Decimal("20900.00")


def test_rate_column_never_wins_over_the_md_count_column():
    """Realny arkusz z Finansów ma OBIE kolumny: „Średnia Stawka MD" i „Ilość MD".

    Bez wykluczenia nagłówków stawkowych wygrywała pierwsza z brzegu i system
    odejmowałby z budżetu 1000 „dni" zamiast 15 — błąd CICHY, bo liczba jest
    poprawna arytmetycznie, tylko opisuje co innego.
    """
    parsed = parse_md_sheet(
        _sheet(
            ["Imię i nazwisko", "Średnia Stawka MD", "Ilość MD"],
            [["Jan Kowalski", 1000, 15]],
        )
    )
    assert parsed.rows[0].md_reported == Decimal("15")


def test_bare_md_header_still_works_when_it_is_the_only_one():
    parsed = parse_md_sheet(_sheet(["Konsultant", "MD"], [["Jan Kowalski", 12]]))
    assert parsed.rows[0].md_reported == Decimal("12")
