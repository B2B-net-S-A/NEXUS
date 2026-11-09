"""Plik Excel raportu BNP: dwa arkusze w układzie szablonu banku.

Kolumny wyliczane są formułami, bo Delivery Lead poprawia plik przed wysyłką
i liczby mają iść za poprawką.
"""

from __future__ import annotations

from datetime import date
from io import BytesIO
from typing import Sequence

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import column_index_from_string, get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core.export_safety import safe_cell
from app.services.bnp_report.calculations import SUPPLIER_NAME, ReportRow

# Nagłówki dosłownie z szablonu banku, razem z ich spacjami.
OPTION_SHEET = "Opcja do Nexusa"
OPTION_HEADERS = (
    "START",
    "CLOSED",
    "SLA (zgodnie z umową 10 DR)",
    "NUMER WNIOSKU RITM",
    "ROLA",
    "SENIORITY",
    "# CV",
    "# CV zgodna SLA",
    "#CV zgodna stawka ",
    "# ODRZUCONYCH CV",
    "# SPOTKAŃ",
    "# ODRZUCONYCH PO SPOTKANIACH",
    "# OFERT",
    "stawka min z oferty ",
    "stawka max  z oferty",
)
FULL_SHEET = "Cały raport"
FULL_HEADERS = (
    "DOSTAWCA",
    "START",
    "CLOSED",
    "SLA (zgodnie z umową 10 DR)",
    "NUMER WNIOSKU RITM",
    "ROLA",
    "SENIORITY",
    "# CV",
    "# CV zgodna SLA",
    "#CV zgodna stawka ",
    "% CV zgodnie z SLA",
    "# RITM zgodna z SLA",
    "RITM zgodne z SLA oraz widełkami (kolumna I oraz J = co najmniej 2)",
    "# ODRZUCONYCH CV",
    "# SPOTKAŃ",
    "# ODRZUCONYCH PO SPOTKANIACH",
    "#spotkań/#CV",
    "#odrzuconych CV/#CV",
    "# OFERT",
    "uwagi",
    "widełki umowne min",
    "widełki umowne max",
    "średnia z umowy ",
    "stawka min z oferty ",
    "stawka max  z oferty",
    "średnia stawka z rekomendacji ",
    "rozbieżność od  średniej umownej ",
    "różnica od górnej granicy widełek vs stawka min ",
    "% różnicy ",
)

_HEADER_FILL = PatternFill("solid", fgColor="00915A")
_HEADER_FONT = Font(bold=True, color="FFFFFF", size=9)
_MISSING_FILL = PatternFill("solid", fgColor="FFF2CC")
_DATE_FORMAT = "DD.MM.YYYY"
_PERCENT_FORMAT = "0%"
_RATIO_FORMAT = "0.00"


def _write_headers(sheet: Worksheet, headers: Sequence[str], width: int = 12) -> None:
    for column, header in enumerate(headers, start=1):
        cell = sheet.cell(row=1, column=column, value=header)
        cell.fill = _HEADER_FILL
        cell.font = _HEADER_FONT
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        sheet.column_dimensions[get_column_letter(column)].width = width
    sheet.row_dimensions[1].height = 62
    sheet.freeze_panes = "A2"


def _put(
    sheet: Worksheet,
    row: int,
    column: int,
    value: object,
    *,
    missing: bool = False,
) -> None:
    cell = sheet.cell(row=row, column=column)
    if isinstance(value, str):
        # Numer zapytania i tytuł wpisują ludzie. `safe_cell` zdejmuje znaki
        # sterujące (wywróciłyby eksport) i rozbraja formuły; typ „s” dopina to,
        # bo openpyxl sam uznałby tekst od „=” za formułę.
        cell.value = safe_cell(value)
        cell.data_type = "s"
    elif value is not None:
        cell.value = value
    if isinstance(value, date):
        cell.number_format = _DATE_FORMAT
    if missing:
        cell.fill = _MISSING_FILL


def _formula(sheet: Worksheet, reference: str, formula: str, number_format: str = "") -> None:
    sheet[reference] = formula
    if number_format:
        sheet[reference].number_format = number_format


def _fill_option_row(sheet: Worksheet, number: int, row: ReportRow) -> None:
    values: list[tuple[object, bool]] = [
        (row.start, False),
        (row.closed, False),
        (row.sla, False),
        (row.ritm, row.ritm is None),
        (row.role, False),
        (row.seniority_label, row.seniority is None),
        (row.cv, False),
        (row.cv_sla, False),
        (row.cv_in_budget, row.cv_in_budget is None),
        (row.rejected_cv, False),
        (row.meetings, False),
        (row.rejected_after_meeting, False),
        (row.offers, False),
        (row.offer_min_md, False),
        (row.offer_max_md, False),
    ]
    for column, (value, missing) in enumerate(values, start=1):
        _put(sheet, number, column, value, missing=missing)


def _fill_full_row(sheet: Worksheet, n: int, row: ReportRow) -> None:
    no_band = row.band_min_md is None
    plain: dict[str, tuple[object, bool]] = {
        "A": (SUPPLIER_NAME, False),
        "B": (row.start, False),
        "C": (row.closed, False),
        "D": (row.sla, False),
        "E": (row.ritm, row.ritm is None),
        "F": (row.role, False),
        "G": (row.seniority_label, row.seniority is None),
        "H": (row.cv, False),
        "I": (row.cv_sla, False),
        "J": (row.cv_in_budget, row.cv_in_budget is None),
        "N": (row.rejected_cv, False),
        "O": (row.meetings, False),
        "P": (row.rejected_after_meeting, False),
        "S": (row.offers, False),
        "U": (row.band_min_md, no_band),
        "V": (row.band_max_md, no_band),
        "X": (row.offer_min_md, False),
        "Y": (row.offer_max_md, False),
    }
    for letter, (value, missing) in plain.items():
        _put(sheet, n, column_index_from_string(letter), value, missing=missing)
    _formula(sheet, f"K{n}", f'=IF(H{n}>0,I{n}/H{n},"")', _PERCENT_FORMAT)
    _formula(sheet, f"L{n}", f"=IF(I{n}>=2,1,0)")
    _formula(sheet, f"M{n}", f'=IF(J{n}="","",IF(AND(I{n}>=2,J{n}>=2),1,0))')
    _formula(sheet, f"Q{n}", f'=IF(H{n}>0,O{n}/H{n},"")', _RATIO_FORMAT)
    _formula(sheet, f"R{n}", f'=IF(H{n}>0,N{n}/H{n},"")', _RATIO_FORMAT)
    _formula(sheet, f"W{n}", f'=IF(OR(U{n}="",V{n}=""),"",AVERAGE(U{n}:V{n}))')
    _formula(sheet, f"Z{n}", f'=IF(OR(X{n}="",Y{n}=""),"",AVERAGE(X{n}:Y{n}))')
    _formula(sheet, f"AA{n}", f'=IF(OR(Z{n}="",W{n}=""),"",(Z{n}-W{n})/W{n})', _PERCENT_FORMAT)
    _formula(sheet, f"AB{n}", f'=IF(OR(V{n}="",X{n}=""),"",X{n}-V{n})')
    _formula(sheet, f"AC{n}", f'=IF(AB{n}="","",AB{n}/V{n})', _PERCENT_FORMAT)


def build_workbook(rows: Sequence[ReportRow]) -> bytes:
    workbook = Workbook()
    option: Worksheet = workbook.active
    option.title = OPTION_SHEET
    full: Worksheet = workbook.create_sheet(FULL_SHEET)
    _write_headers(option, OPTION_HEADERS)
    _write_headers(full, FULL_HEADERS)
    option.column_dimensions["E"].width = 30
    full.column_dimensions["F"].width = 30
    for index, row in enumerate(rows, start=2):
        _fill_option_row(option, index, row)
        _fill_full_row(full, index, row)
    buffer = BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def report_filename(month: str) -> str:
    return f"Raport BNP {month}.xlsx"
