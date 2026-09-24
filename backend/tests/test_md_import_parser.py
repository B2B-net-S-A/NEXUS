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


@pytest.mark.parametrize(
    "md_cell,reason_fragment",
    [
        ("NaN", "nie jest skończoną liczbą"),
        ("Infinity", "nie jest skończoną liczbą"),
        ("-inf", "nie jest skończoną liczbą"),
        (-3, "ujemna liczba MD"),
        (5000, "powyżej 1000"),
    ],
)
def test_non_finite_or_absurd_md_goes_to_skipped_rows(md_cell, reason_fragment):
    """SCV-04: `Decimal("NaN")` przechodził przez parser bez wyjątku.

    NaN rozlewał się na pozostałość wspólnej puli MD (każde działanie z NaN
    daje NaN), a nieskończoność wywracała zapis do kolumny NUMERIC. Wiersz ma
    trafić do pominiętych z numerem i powodem, a nie do rozliczenia.
    """
    content = _book(
        [
            ["Konsultant", "MD"],
            ["Jan Kowalski", 10],
            ["Anna Nowak", md_cell],
        ]
    )
    parsed = parse_md_sheet(content)
    assert [row.consultant_name for row in parsed.rows] == ["Jan Kowalski"]
    assert all(row.md_reported.is_finite() for row in parsed.rows)
    assert len(parsed.skipped_rows) == 1
    skipped = parsed.skipped_rows[0]
    assert skipped["row"] == 3
    assert skipped["consultant_name"] == "Anna Nowak"
    assert reason_fragment in skipped["reason"]


def test_non_finite_invoice_amount_goes_to_skipped_rows():
    content = _book(
        [
            ["Konsultant", "MD", "Uwagi", "Faktura"],
            ["Jan Kowalski", 10, "SAP 4500719650", "1 000,00 zł"],
            ["Anna Nowak", 5, "SAP 4500719650", "NaN"],
        ]
    )
    parsed = parse_md_sheet(content)
    assert [row.consultant_name for row in parsed.rows] == ["Jan Kowalski"]
    assert parsed.rows[0].invoice_amount == Decimal("1000.00")
    assert parsed.skipped_rows == [
        {
            "row": 3,
            "reason": "kwota faktury nie jest skończoną liczbą ('NaN')",
            "consultant_name": "Anna Nowak",
        }
    ]


def test_md_boundaries_are_inclusive():
    content = _book([["Konsultant", "MD"], ["Jan Kowalski", 0], ["Anna Nowak", 1000]])
    parsed = parse_md_sheet(content)
    assert [row.md_reported for row in parsed.rows] == [Decimal("0"), Decimal("1000")]
    assert parsed.skipped_rows == []


# ── Audyt 24.09.2026 (S6): formaty kwot i nieczytelna faktura ───────────────


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("20.900,00 zł", Decimal("20900.00")),
        ("1,234.56", Decimal("1234.56")),
        ("1.234.567", Decimal("1234567")),
        ("1,234,567", Decimal("1234567")),
        ("20 900,00 zł", Decimal("20900.00")),
        ("20\u202f900,50 PLN", Decimal("20900.50")),
    ],
)
def test_money_with_thousand_dots_or_english_format_is_read(raw, expected):
    from app.services.md_import_parser import parse_money_value

    assert parse_money_value(raw) == expected


def test_unreadable_invoice_cell_goes_to_skipped_rows_with_a_reason():
    """Niepusta, nieczytelna kwota faktury nie znika po cichu."""
    content = _book(
        [
            ["Konsultant", "MD", "Uwagi", "Faktura"],
            ["Jan Kowalski", 10, "SAP 4500719650", "20.900,00 zł"],
            ["Anna Nowak", 5, "SAP 4500719650", "do ustalenia"],
            ["Ewa Lis", 3, "SAP 4500719650", "-"],
        ]
    )
    parsed = parse_md_sheet(content)
    assert [row.consultant_name for row in parsed.rows] == ["Jan Kowalski", "Ewa Lis"]
    assert parsed.rows[0].invoice_amount == Decimal("20900.00")
    assert parsed.rows[1].invoice_amount is None
    assert parsed.skipped_rows == [
        {
            "row": 3,
            "reason": "nieczytelna kwota faktury ('do ustalenia')",
            "consultant_name": "Anna Nowak",
        }
    ]


def test_import_route_parses_the_sheet_off_the_event_loop():
    """N6 (audyt 24.09.2026): openpyxl parsuje synchronicznie — trasa importu
    woła parser w wątku, nie w pętli zdarzeń jedynego procesu uvicorna."""
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1] / "app" / "api" / "md_consumption.py"
    ).read_text(encoding="utf-8")
    assert "run_in_threadpool(parse_md_sheet, payload)" in source
    assert "= parse_md_sheet(" not in source
