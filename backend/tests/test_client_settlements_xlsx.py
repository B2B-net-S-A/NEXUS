"""Skoroszyt z atrybutem ``showZeroes`` w widoku arkusza (próba VI–VIII 2026). Bez bazy.

Plik zapisany poza Excelem ma ``showZeroes`` zamiast ``showZeros``; openpyxl w trybie
``read_only`` rzucał ``TypeError`` przy czytaniu wierszy i wywracał mail z poczty
rozliczeń. Dane fikcyjne.
"""

from __future__ import annotations

import io
import zipfile
from datetime import date, datetime
from decimal import Decimal

import openpyxl

from app.services.client_settlements import (
    kcp,
    rcp_bnp,
    redmine_timelog,
    report_ca,
    timesheet,
    timesheet_fieldglass,
    vendor_file,
    xlsx,
)


def _book(rows: list[list]) -> bytes:
    workbook = openpyxl.Workbook()
    for row in rows:
        workbook.active.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _with_show_zeroes(content: bytes) -> bytes:
    source = zipfile.ZipFile(io.BytesIO(content))
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as target:
        for item in source.infolist():
            data = source.read(item.filename)
            if item.filename == "xl/worksheets/sheet1.xml":
                data = data.replace(b"<sheetView ", b'<sheetView showZeroes="0" ', 1)
            target.writestr(item, data)
    return out.getvalue()


TIME_SHEET = [
    [None, "Time Sheet"],
    [None, "Project Name", "ALFA"],
    [None, "Consultant(s)", "Jan Testowy"],
    [None, "Date from", date(2026, 7, 1)],
    [None, "Date to", date(2026, 7, 31)],
    [None, "Date", "Project", "Description", "Total Hours", "Billable"],
    [None, datetime(2026, 7, 1), None, "Zadanie", 8, 8],
    [None, datetime(2026, 7, 2), None, "Zadanie", 6, 6],
]


def test_bez_clean_openpyxl_wywraca_odczyt_wierszy():
    """Stan sprzed poprawki: błąd wychodzi dopiero przy ``iter_rows``."""

    content = _with_show_zeroes(_book(TIME_SHEET))
    workbook = openpyxl.load_workbook(io.BytesIO(content), read_only=True)
    try:
        raised = False
        try:
            list(workbook.worksheets[0].iter_rows(values_only=True))
        except TypeError:
            raised = True
        assert raised
    finally:
        workbook.close()


def test_clean_usuwa_atrybut_i_time_sheet_czyta_sie_jak_bez_niego():
    plain = _book(TIME_SHEET)
    content = _with_show_zeroes(plain)
    assert b"showZeroes" not in zipfile.ZipFile(io.BytesIO(xlsx.clean(content))).read(
        "xl/worksheets/sheet1.xml"
    )
    parsed = timesheet.parse(content, timesheet.XLSX)
    assert parsed is not None and parsed.total_hours == Decimal("14")
    assert parsed.total_hours == timesheet.parse(plain, timesheet.XLSX).total_hours


def test_plik_bez_atrybutu_i_nie_zip_zostaja_bez_zmian():
    plain = _book(TIME_SHEET)
    assert xlsx.clean(plain) is plain
    assert xlsx.clean(b"not a zip") == b"not a zip"


def test_czytniki_read_only_nie_wywracaja_sie_na_takim_pliku():
    content = _with_show_zeroes(_book([["Inny arkusz"], [1, 2, 3]]))
    # Każdy z tych czytników otwiera arkusz w trybie ``read_only``: obcy plik = brak odczytu.
    assert rcp_bnp.parse(content, timesheet.XLSX) is None
    assert report_ca.parse(content, timesheet.XLSX) is None
    assert vendor_file.parse(content, timesheet.XLSX) is None
    assert timesheet_fieldglass.parse(content, timesheet.XLSX) is None
    assert kcp.parse(content, timesheet.XLSX) is None
    assert redmine_timelog.parse(content, timesheet.XLSX) is None
