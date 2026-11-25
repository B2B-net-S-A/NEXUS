"""Raport godzin konsultanta u klienta BIK bez bazy. Dane fikcyjne.

Osoba „Jan Testowy”, zamówienie „45000xxxxx”, zadania „ABC-1”… Układ jak
w plikach z archiwum rozliczeń IX–XI 2026: szablon „Rozliczenie czasu pracy”
(nowy z „Numer jiry” i „Suma godzin”, starszy z sumą „Liczba godzin”),
ten sam szablon w PDF i tabela dni „Data · Dzień · Ilość godzin”.
"""

from __future__ import annotations

import io
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace

import openpyxl

from app.services.client_settlements import (
    rcp_bnp,
    rules_catalog,
    service,
    timesheet,
    timesheet_bik,
)

MONTH = "2026-10"
XLSX = timesheet_bik.XLSX


def _rules(**levels: str) -> dict:
    rules = rules_catalog.effective({})
    for key, level in levels.items():
        rules[key.replace("__", ".")]["level"] = level
    return rules


def _book(
    days: list[tuple[int, float]],
    *,
    name: object = "Jan Testowy",
    month: object = datetime(2026, 10, 1),
    total: object = "sum",
    hidden: tuple[int, ...] = (),
) -> bytes:
    """Nowy szablon BIK. ``total``: liczba, ``"sum"`` (wzór bez zapisanej
    wartości, jak w plikach spoza Excela) albo ``None`` (brak wiersza)."""

    wb = openpyxl.Workbook()
    ws = wb.active
    ws["B7"] = "Rozliczenie czasu pracy"
    ws["B9"], ws["C9"] = "Imię i nazwisko", name
    ws["B10"], ws["C10"] = "Miesiąc", month
    ws["B11"], ws["C11"] = "Numer zamówienia", "45000xxxxx"
    ws["B14"], ws["C14"], ws["D14"], ws["E14"] = (
        "Numer jiry",
        "Nazwa zadania",
        "Data",
        "Liczba godzin",
    )
    row = 15
    for index, (day, hours) in enumerate(days):
        ws.cell(row, 2, f"ABC-{index + 1}")
        ws.cell(row, 3, "Implementacja i testy")
        ws.cell(row, 4, datetime(2026, 10, day))
        ws.cell(row, 5, hours)
        if index in hidden:
            ws.row_dimensions[row].hidden = True
        row += 1
    if total is not None:
        ws.cell(row, 4, "Suma godzin")
        ws.cell(row, 5, f"=SUM(E15:E{row - 1})" if total == "sum" else total)
    ws.cell(row + 2, 4, "MDs narastająco 2026:")
    ws.cell(row + 2, 5, 150.5)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _evaluate(parsed, rules=None, person="Jan Testowy"):
    return timesheet_bik.evaluate(
        parsed,
        month=MONTH,
        person_name=person,
        rules=rules or _rules(),
        working_days=22,
    )


def _titles(result) -> list[str]:
    return [c["title"] for g in result.groups for c in g["checks"]]


# ── Szablon BIK (xlsx) ───────────────────────────────────────────────────────


def test_good_report_counts_md_from_rows_and_checks_pass() -> None:
    content = _book([(1, 8), (2, 6), (2, 2), (5, 8)], total=24)

    parsed = timesheet_bik.parse(content, XLSX)
    result = _evaluate(parsed)

    assert parsed.month == MONTH
    assert parsed.order_number == "45000xxxxx"
    assert parsed.declared_total == Decimal("24.00")
    assert len(parsed.entries) == 4
    assert result.md_regular == Decimal("3.000")
    assert result.md_extra == Decimal("0")
    assert not result.blocking and not result.warn
    titles = _titles(result)
    assert "Imię i nazwisko jak w kontrakcie" in titles
    assert "Godziny policzone od nowa" in titles
    assert "Najwięcej w jednym dniu: 8 h" in titles


def test_other_readers_do_not_take_bik_report() -> None:
    """Przed tym odczytem BIK szedł do ogólnych czytników: BNP dawało 0 MD
    ze statusem „ok”, Time Sheet E6.2 nic. Kolejność w ``_proof`` się trzyma."""

    content = _book([(1, 8)], total=8)

    assert rcp_bnp.parse(content, XLSX) is None
    assert timesheet.parse(content, XLSX) is None


def test_sum_formula_without_saved_value_counts_rows() -> None:
    """Plik bez sumy: wzór bez zapisanej wartości, godziny liczymy z wierszy."""

    parsed = timesheet_bik.parse(_book([(1, 8), (2, 7.5)]), XLSX)
    result = _evaluate(parsed)

    assert parsed.declared_total is None
    assert result.md_regular == Decimal("1.938")
    assert "Godziny policzone od nowa" in _titles(result)


def test_report_without_total_row_counts_rows() -> None:
    parsed = timesheet_bik.parse(_book([(1, 8), (2, 8)], total=None), XLSX)

    assert parsed.declared_total is None
    assert _evaluate(parsed).md_regular == Decimal("2.000")


def test_total_other_than_rows_is_a_rule_failure() -> None:
    parsed = timesheet_bik.parse(_book([(1, 8), (2, 8)], total=24), XLSX)
    result = _evaluate(parsed, _rules(fields__md_hours="block"))

    assert result.md_regular == Decimal("2.000")
    assert result.blocking
    assert "„Suma godzin” inna niż suma wierszy" in _titles(result)


def test_hidden_rows_are_counted_with_warning() -> None:
    """Wrzesień 2026: rozliczenia widziały 140 h, bo część wierszy była ukryta."""

    parsed = timesheet_bik.parse(_book([(1, 8), (2, 8), (5, 4)], hidden=(2,)), XLSX)
    result = _evaluate(parsed)

    assert result.md_regular == Decimal("2.500")
    assert parsed.hidden_hours == Decimal("4.00")
    assert result.warn
    assert "Ukryte wiersze z godzinami: 4 h" in _titles(result)


def test_empty_file_has_no_md_and_is_blank_template() -> None:
    """Pusty szablon (wzór odesłany przez rozliczenia w wątku): bez MD."""

    content = _book([], name=None, month=None, total=0)

    parsed = timesheet_bik.parse(content, XLSX)
    result = _evaluate(parsed)

    assert parsed is not None and not parsed.entries
    assert timesheet_bik.is_blank(content, XLSX)
    assert result.md_regular is None
    assert result.warn
    assert _titles(result) == ["Raport godzin bez godzin"]


def test_filled_report_is_not_blank() -> None:
    assert not timesheet_bik.is_blank(_book([(1, 8)]), XLSX)


def test_wrong_month_and_other_name_fail_rules() -> None:
    parsed = timesheet_bik.parse(
        _book([(1, 8)], month=datetime(2026, 9, 1), name="Anna Inna"), XLSX
    )
    result = _evaluate(parsed, _rules(proof__month="block", proof__name_match="warn"))

    assert result.blocking
    titles = _titles(result)
    assert "Raport godzin za inny miesiąc" in titles
    assert "Inne imię lub nazwisko niż w kontrakcie" in titles


def test_month_name_without_year_takes_year_from_rows() -> None:
    parsed = timesheet_bik.parse(_book([(1, 8)], month="Październik"), XLSX)

    assert parsed.month == MONTH


def test_old_template_with_total_in_liczba_godzin_row() -> None:
    rows: list[list[object]] = [
        [None, "Roliczenie czasu pracy "],
        [None, "Imię i nazwisko", "Jan Testowy"],
        [None, "Miesiąc", datetime(2026, 10, 1)],
        [None, "Numer zamówienia", 4500000000],
        [None, "Nazwa zadania", "Data", "Liczba godzin"],
        [None, "Rozwój", datetime(2026, 10, 1), 8],
        [None, "Rozwój", datetime(2026, 10, 2), 8],
        [None, None, None, None],
        [None, None, "Liczba godzin", 16],
        [None, "Zużycie MD", "120/200"],
    ]

    parsed = timesheet_bik.parse_rows(rows)

    assert parsed.declared_total == Decimal("16.00")
    assert parsed.order_number == "4500000000"
    assert _evaluate(parsed).md_regular == Decimal("2.000")


def test_day_table_without_title_and_name() -> None:
    """Konsultant bez szablonu: tabela dni, suma pod tabelą bez etykiety."""

    rows: list[list[object]] = [["Data", "Dzień", "Ilość godzin"]]
    for day in range(1, 8):
        stamp = datetime(2026, 10, day)
        weekend = stamp.weekday() >= 5
        rows.append([stamp, "sobota" if weekend else "dzień", None if weekend else 8])
    rows += [[None, None, None], [None, None, 40]]

    parsed = timesheet_bik.parse_rows(rows)
    result = _evaluate(parsed, _rules(proof__name_match="warn"))

    assert parsed.declared_total == Decimal("40.00")
    assert result.md_regular == Decimal("5.000")
    assert "Miesiąc z dat wierszy: październik 2026" in _titles(result)
    assert "Raport godzin bez imienia i nazwiska" in _titles(result)


def test_day_table_total_row_with_label_is_not_an_entry() -> None:
    """Tabela dni „Dzień · Data · Liczba godzin” z wierszem „Łącznie” pod nią
    (próba rozliczeń 22.11.2026: suma liczona jako wpis, MD podwójne)."""

    rows: list[list[object]] = [
        ["Jan Testowy"],
        ["Klient projektu:", "Klient Testowy"],
        ["Dzień", "Data", "Liczba godzin"],
    ]
    for day in range(1, 8):
        stamp = datetime(2026, 10, day)
        weekend = stamp.weekday() >= 5
        rows.append(["sobota" if weekend else "dzień", stamp, 0 if weekend else 8])
    rows.append([None, "Łącznie", 40])

    parsed = timesheet_bik.parse_rows(rows)
    result = _evaluate(parsed, _rules(proof__name_match="warn"))

    assert parsed.rows_hours == Decimal("40")
    assert parsed.declared_total == Decimal("40.00")
    assert result.md_regular == Decimal("5.000")


def test_template_sum_row_without_label_is_not_an_entry() -> None:
    """Suma pod tabelą szablonu bez etykiety (sama liczba w kolumnie godzin)."""

    rows: list[list[object]] = [
        ["Rozliczenie czasu pracy"],
        ["Imię i nazwisko", "Jan Testowy"],
        ["Miesiąc", datetime(2026, 10, 1)],
        ["Numer jiry", "Nazwa zadania", "Data", "Liczba godzin"],
        ["ABC-1", "Zadanie", datetime(2026, 10, 1), 8],
        ["ABC-2", "Zadanie", datetime(2026, 10, 2), 8],
        [None, None, None, 16],
    ]

    parsed = timesheet_bik.parse_rows(rows)

    assert parsed.rows_hours == Decimal("16")
    assert parsed.declared_total == Decimal("16.00")


def test_sheet_with_data_column_but_no_bik_layout_is_not_read() -> None:
    rows = [["Data", "Opis", "Liczba godzin"], [datetime(2026, 10, 1), "x", 8]]

    assert timesheet_bik.parse_rows(rows) is None


def test_other_file_types_are_not_read() -> None:
    assert timesheet_bik.parse(b"not a sheet", XLSX) is None
    assert timesheet_bik.parse(b"x", "image/png") is None


# ── Szablon BIK w PDF (tabele z pdfplumber) ─────────────────────────────────


def _pdf_rows(*body: list[object], total: object = "16") -> list[list[object]]:
    return [
        ["Imię i nazwisko", "Jan Testowy"],
        ["Miesiąc", "październik 2026"],
        ["Numer zamówienia", "45000xxxxx"],
        ["Numer jira", "Nazwa zadania / Zakres działań", "Data", "Liczba godzin"],
        *body,
        ["", "", "Suma godzin", total],
    ]


def test_pdf_rows_with_repeated_header_on_next_page() -> None:
    rows = _pdf_rows(
        ["ABC-1", "Analiza", "01.10.2026", "4"],
        ["—", "Spotkania: daily", "01.10.2026", "0,5"],
        ["Numer jira", "Nazwa zadania / Zakres działań", "Data", "Liczba godzin"],
        ["ABC-2", "Testy", "02.10.2026", "7,5"],
        ["ABC-3", "Wdrożenie", "05.10.2026", "4"],
    )

    parsed = timesheet_bik.parse_rows(rows, source="pdf", title=True)
    result = _evaluate(parsed, _rules(fields__md_hours="block"))

    assert parsed.month == MONTH
    assert parsed.rows_match_total
    assert result.md_regular == Decimal("2.000")
    assert not result.blocking


def test_pdf_with_overflowing_rows_takes_md_from_total_with_warning() -> None:
    """Długi opis wychodzi w PDF poza komórkę i psuje datę i godziny wiersza."""

    rows = _pdf_rows(
        ["ABC-1", "Analiza", "01.10.2026", "8"],
        ["ABC-2", "Bardzo długi opis zadan", "ia0 2.1 0.2 0 2 6", "te8sty"],
    )

    parsed = timesheet_bik.parse_rows(rows, source="pdf", title=True)
    result = _evaluate(parsed, _rules(fields__md_hours="block"))

    assert parsed.rows_hours == Decimal("8.00")
    assert result.md_regular == Decimal("2.000")
    assert not result.blocking and result.warn
    assert "MD z „Sumy godzin”: część wierszy PDF nieczytelna" in _titles(result)


def test_pdf_short_month_and_day_format() -> None:
    """Pole „Miesiąc” jako „paź 26” i daty „1-10” (formaty Excela w PDF)."""

    rows = _pdf_rows(
        ["", "Rozwój", "1-10", "8"],
        ["", "Rozwój", "2-10", "8"],
    )
    rows[1] = ["Miesiąc", "paź 26"]

    parsed = timesheet_bik.parse_rows(rows, source="pdf", title=True)

    assert parsed.month == MONTH
    assert [e.day.day for e in parsed.entries] == [1, 2]
    assert _evaluate(parsed).md_regular == Decimal("2.000")


def test_pdf_without_title_is_not_read() -> None:
    assert timesheet_bik.parse(b"%PDF-1.4 broken", timesheet_bik.PDF) is None


# ── Wybór pliku miesiąca ────────────────────────────────────────────────────


async def test_pick_report_skips_blank_template(tmp_path, monkeypatch) -> None:
    """IX 2026: konsultant wysłał tabelę dni, a dzień później odpowiedź z pustym
    szablonem z cytowanego wątku. Nowszy pusty plik nie może wygrać."""

    blank = tmp_path / "blank.xlsx"
    blank.write_bytes(_book([], name=None, month=None, total=0))
    filled = tmp_path / "filled.xlsx"
    filled.write_bytes(_book([(1, 8)]))
    monkeypatch.setattr(service.portal_documents, "path_for", lambda p: tmp_path / p)
    newest_first = [
        SimpleNamespace(id=2, mime=XLSX, file_path="blank.xlsx"),
        SimpleNamespace(id=1, mime=XLSX, file_path="filled.xlsx"),
    ]

    picked = await service._pick_report(newest_first)

    assert picked.id == 1


async def test_pick_report_keeps_only_file_even_if_blank(tmp_path, monkeypatch) -> None:
    blank = tmp_path / "blank.xlsx"
    blank.write_bytes(_book([], name=None, month=None, total=0))
    monkeypatch.setattr(service.portal_documents, "path_for", lambda p: tmp_path / p)

    picked = await service._pick_report(
        [SimpleNamespace(id=2, mime=XLSX, file_path="blank.xlsx")]
    )

    assert picked.id == 2


# ── Wariant z próby VI–VIII 2026: „Czas (godz.)”, Word, osoba w nazwie pliku ──


def test_naglowek_czas_godz_i_osoba_z_nazwy_pliku() -> None:
    rows: list[list[object]] = [
        ["Rozliczenie czasu pracy"],
        ["NR", "Zadanie", "Data", "Czas- (godz.)"],
        [1, "ABC-1, ABC-2", datetime(2026, 10, 1), 8],
        [2, None, datetime(2026, 10, 3), None],
        [3, "ABC-3", datetime(2026, 10, 2), 6],
        [None, None, "Suma", 14],
    ]
    parsed = timesheet_bik.parse_rows(rows)
    assert parsed is not None and parsed.rows_hours == Decimal("14")
    named = timesheet_bik.evaluate(
        parsed,
        month=MONTH,
        person_name="Jan Testowy",
        rules=_rules(),
        working_days=22,
        file_name="Rozliczenie_Jan_Testowy_pazdziernik_2026.xlsx",
    )
    assert named.md_regular == Decimal("1.750")
    assert "Imię i nazwisko z nazwy pliku jak w kontrakcie" in _titles(named)
    assert "Raport godzin bez imienia i nazwiska" not in _titles(named)
    other = timesheet_bik.evaluate(
        parsed,
        month=MONTH,
        person_name="Jan Testowy",
        rules=_rules(),
        working_days=22,
        file_name="Rozliczenie_Anna_Inna.xlsx",
    )
    assert "Raport godzin bez imienia i nazwiska" in _titles(other)


def test_szablon_w_wordzie() -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("Rozliczenie czasu pracy zamówienia numer 1/2026")
    document.add_paragraph("Za miesiąc październik 2026")
    document.add_paragraph("Imię i nazwisko: Jan Testowy")
    table = document.add_table(rows=0, cols=3)
    for cells in (
        ("Zadanie", "Data", "Czas (godz.)"),
        ("ABC-1, ABC-2", "2026-10-01", "8"),
        ("Planowanie", "2026-10-02", "6"),
        ("", "Suma", "14 h"),
    ):
        row = table.add_row().cells
        for cell, text in zip(row, cells):
            cell.text = text
    document.add_paragraph("Liczba MDs narastająco w 2026: 10,5 MDs")
    buf = io.BytesIO()
    document.save(buf)

    parsed = timesheet_bik.parse(buf.getvalue(), timesheet_bik.DOCX)
    assert parsed is not None
    assert parsed.month == MONTH
    assert parsed.declared_total == Decimal("14")
    result = _evaluate(parsed)
    assert result.md_regular == Decimal("1.750")
    assert "Imię i nazwisko jak w kontrakcie" in _titles(result)


def test_word_bez_tytulu_bik_nie_jest_raportem() -> None:
    import docx

    document = docx.Document()
    document.add_paragraph("Protokół odbioru")
    buf = io.BytesIO()
    document.save(buf)
    assert timesheet_bik.parse(buf.getvalue(), timesheet_bik.DOCX) is None
