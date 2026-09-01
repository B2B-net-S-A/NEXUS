"""Parser arkusza MD — bez bazy i bez aplikacji (czysty moduł).

Arkusze z Finansów przychodzą w różnych kształtach, więc te testy pilnują
tolerancji parsera: arkusz tytułowy przed danymi, wiersze nad nagłówkiem,
polski przecinek dziesiętny, synonimy nagłówków.
"""

from __future__ import annotations

import io
from decimal import Decimal

import pytest
from openpyxl import Workbook

from app.services.md_import_parser import (
    MdSheetFormatError,
    parse_md_sheet,
    parse_md_value,
)


def _book(
    rows: list[list], *, title_sheet: bool = False, sheet_name: str = "Arkusz"
) -> bytes:
    wb = Workbook()
    if title_sheet:
        wb.active.title = "Tytul"
        wb.active["A1"] = "Raport miesięczny"
        ws = wb.create_sheet(sheet_name)
    else:
        ws = wb.active
        ws.title = sheet_name
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


@pytest.mark.parametrize(
    "raw,expected",
    [
        (15, Decimal("15")),
        (12.5, Decimal("12.5")),
        ("12,5", Decimal("12.5")),
        ("1 234,5", Decimal("1234.5")),
        ("", None),
        (None, None),
        ("n/d", None),
        (True, None),
    ],
)
def test_parse_md_value(raw, expected):
    """Bool jest odrzucany celowo: w Excelu TRUE nie jest liczbą MD."""
    assert parse_md_value(raw) == expected


@pytest.mark.parametrize(
    "name_header,md_header",
    [
        ("Konsultant", "MD"),
        ("Imię i nazwisko", "Osobodni"),
        ("Pracownik", "Man-days"),
        ("Nazwisko i imię", "MD zaraportowane"),
    ],
)
def test_header_synonyms(name_header, md_header):
    content = _book([[name_header, md_header], ["Jan Kowalski", 10]])
    parsed = parse_md_sheet(content)
    assert [r.consultant_name for r in parsed.rows] == ["Jan Kowalski"]
    assert parsed.rows[0].md_reported == Decimal("10")


def test_skips_title_rows_and_finds_header_below():
    content = _book(
        [
            ["Raport MD za lipiec"],
            [],
            ["Lp.", "Konsultant", "MD"],
            [1, "Jan Kowalski", 15],
            [2, "Anna Nowak", "12,5"],
        ]
    )
    parsed = parse_md_sheet(content)
    assert parsed.header_row == 3
    assert [r.row_number for r in parsed.rows] == [4, 5]
    assert parsed.rows[1].md_reported == Decimal("12.5")


def test_uses_the_first_sheet_that_has_a_recognizable_table():
    content = _book(
        [["Konsultant", "MD"], ["Jan Kowalski", 8]],
        title_sheet=True,
        sheet_name="Dane",
    )
    parsed = parse_md_sheet(content)
    assert parsed.sheet_name == "Dane"
    assert len(parsed.rows) == 1


def test_reports_skipped_rows_instead_of_dropping_them_silently():
    """Wiersz nie do odczytania musi być WIDOCZNY — cicha strata to zła faktura."""
    content = _book(
        [
            ["Konsultant", "MD"],
            ["", 5],
            ["Anna Bez Liczby", "brak"],
            ["Jan Kowalski", 3],
        ]
    )
    parsed = parse_md_sheet(content)
    assert [r.consultant_name for r in parsed.rows] == ["Jan Kowalski"]
    assert len(parsed.skipped_rows) == 2
    reasons = " ".join(s["reason"] for s in parsed.skipped_rows)
    assert "nazwiska" in reasons and "MD" in reasons


def test_specific_md_header_wins_over_the_generic_one():
    """Arkusz z „MD" i „MD zaraportowane" musi wybrać tę drugą kolumnę."""
    content = _book(
        [["Konsultant", "MD", "MD zaraportowane"], ["Jan Kowalski", 99, 15]]
    )
    parsed = parse_md_sheet(content)
    assert parsed.rows[0].md_reported == Decimal("15")


def test_file_without_recognizable_table_is_rejected():
    content = _book([["Coś", "Innego"], ["a", "b"]])
    with pytest.raises(MdSheetFormatError):
        parse_md_sheet(content)


def test_corrupt_file_is_rejected_with_a_readable_message():
    with pytest.raises(MdSheetFormatError) as exc:
        parse_md_sheet(b"to nie jest xlsx")
    assert "XLSX" in str(exc.value)
