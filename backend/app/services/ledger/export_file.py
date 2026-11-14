"""Plik paczki księgi do Symfonii FK (K3b) — czyste funkcje renderujące.

Formatu importu Symfonii FK jeszcze nie znamy (próbka od Finansów — na nią
czeka też paczka E2), więc są dwa formaty neutralne jak w E2: XLSX i CSV
z wierszem na pozycję dekretu. Dopisanie formatu Symfonii = nowa klasa
i wpis w ``FORMATS``. Tekst z danych idzie przez ``safe_row`` / ``safe_cell``
(komórka od ``= + - @`` nie stanie się formułą w arkuszu).
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any, Optional, Protocol

from openpyxl import Workbook
from openpyxl.styles import Font

from app.core.export_safety import safe_cell, safe_row


@dataclass(frozen=True)
class ExportLine:
    """Jedna pozycja dekretu w pliku paczki."""

    journal_no: int
    number: str
    doc_type: str
    doc_date: date
    op_date: date
    document_description: str
    line_no: int
    account: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    description: str
    mpk: Optional[str]
    counterparty: Optional[str]
    tax_id: Optional[str]
    symfonia_id: Optional[str]
    currency: str
    amount_cur: Optional[Decimal]
    fx_rate: Optional[Decimal]
    fx_date: Optional[date]
    reverses: Optional[str]
    ksef_number: Optional[str]


#: Kolumny formatu neutralnego (kolejność = kolejność w pliku).
COLUMNS: tuple[tuple[str, str], ...] = (
    ("journal_no", "Nr w dzienniku NEXUSA"),
    ("number", "Numer dokumentu"),
    ("doc_type", "Typ"),
    ("doc_date", "Data dokumentu"),
    ("op_date", "Data operacji"),
    ("document_description", "Opis dokumentu"),
    ("line_no", "Pozycja"),
    ("account", "Konto"),
    ("debit", "Wn"),
    ("credit", "Ma"),
    ("description", "Opis pozycji"),
    ("mpk", "MPK"),
    ("counterparty", "Kontrahent"),
    ("tax_id", "NIP / VAT UE"),
    ("symfonia_id", "ID Symfonii kontrahenta"),
    ("currency", "Waluta"),
    ("amount_cur", "Kwota w walucie"),
    ("fx_rate", "Kurs"),
    ("fx_date", "Data kursu"),
    ("reverses", "Storno dokumentu"),
    ("ksef_number", "Numer KSeF"),
)
_NUMBER_FORMATS: dict[str, str] = {
    "debit": "#,##0.00",
    "credit": "#,##0.00",
    "amount_cur": "#,##0.00",
    "fx_rate": "0.000000",
    "doc_date": "yyyy-mm-dd",
    "op_date": "yyyy-mm-dd",
    "fx_date": "yyyy-mm-dd",
}


def money(grosze: Optional[int]) -> Optional[Decimal]:
    """Grosze → złote z dwoma miejscami (``None`` zostaje ``None``)."""

    if grosze is None:
        return None
    return (Decimal(grosze) / 100).quantize(Decimal("0.01"))


class ExportFormat(Protocol):
    key: str
    label: str
    extension: str
    media_type: str

    def render(self, lines: list[ExportLine]) -> bytes: ...


def _values(line: ExportLine) -> list[Any]:
    return [getattr(line, name) for name, _ in COLUMNS]


class NeutralXlsx:
    key = "neutral_xlsx"
    label = "Arkusz XLSX (format neutralny)"
    extension = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render(self, lines: list[ExportLine]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dokumenty"
        sheet.append([label for _, label in COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        formats = {
            index + 1: _NUMBER_FORMATS[name]
            for index, (name, _) in enumerate(COLUMNS)
            if name in _NUMBER_FORMATS
        }
        for line in lines:
            sheet.append(safe_row(_values(line)))
            row = sheet.max_row
            for column, number_format in formats.items():
                sheet.cell(row=row, column=column).number_format = number_format
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()


def _csv_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f").replace(".", ",")
    if isinstance(value, date):
        return value.isoformat()
    if value is None:
        return ""
    return safe_cell(value)


class NeutralCsv:
    key = "neutral_csv"
    label = "CSV ze średnikiem (format neutralny)"
    extension = "csv"
    media_type = "text/csv; charset=utf-8"

    def render(self, lines: list[ExportLine]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow([label for _, label in COLUMNS])
        for line in lines:
            writer.writerow([_csv_cell(value) for value in _values(line)])
        # BOM: polski Excel otwiera wtedy plik w UTF-8.
        return buffer.getvalue().encode("utf-8-sig")


FORMATS: dict[str, ExportFormat] = {
    item.key: item for item in (NeutralXlsx(), NeutralCsv())
}
DEFAULT_FORMAT = NeutralXlsx.key
