"""Formaty pliku eksportu dekretów do Symfonii FK (E2).

Formatu importu Symfonii FK jeszcze nie znamy (czekamy na próbkę od Finansów),
więc są dwa formaty neutralne: XLSX i CSV z wierszem na pozycję dekretu.
Format to jedna klasa z ``key``, ``label``, ``extension``, ``media_type``
i ``render(rows) -> bytes``; dopisanie formatu Symfonii = nowa klasa i wpis
w ``FORMATS``. Każdy tekst idzie przez ``safe_cell`` (komórki od ``= + - @``
nie staną się formułą w arkuszu).
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
class ExportRow:
    """Jedna pozycja dekretu w pliku."""

    register: str
    doc_type: str
    invoice_number: Optional[str]
    ksef_number: Optional[str]
    issue_date: Optional[date]
    received_date: date
    counterparty: Optional[str]
    nip: Optional[str]
    symfonia_id: Optional[str]
    account: str
    debit: Optional[Decimal]
    credit: Optional[Decimal]
    description: str
    vat_rate: Optional[str]
    deduction: Optional[str]


#: Kolumny formatu neutralnego (kolejność = kolejność w pliku).
COLUMNS: tuple[tuple[str, str], ...] = (
    ("register", "Rejestr"),
    ("doc_type", "Typ dokumentu"),
    ("invoice_number", "Numer faktury"),
    ("ksef_number", "Numer KSeF"),
    ("issue_date", "Data wystawienia"),
    ("received_date", "Data wpływu"),
    ("counterparty", "Kontrahent"),
    ("nip", "NIP"),
    ("symfonia_id", "ID Symfonii kontrahenta"),
    ("account", "Konto"),
    ("debit", "Wn"),
    ("credit", "Ma"),
    ("description", "Opis"),
    ("vat_rate", "Stawka VAT"),
    ("deduction", "Odliczenie"),
)


class ExportFormat(Protocol):
    key: str
    label: str
    extension: str
    media_type: str

    def render(self, rows: list[ExportRow]) -> bytes: ...


def _values(row: ExportRow) -> list[Any]:
    return [getattr(row, name) for name, _ in COLUMNS]


class NeutralXlsx:
    key = "neutral_xlsx"
    label = "Arkusz XLSX (format neutralny)"
    extension = "xlsx"
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    def render(self, rows: list[ExportRow]) -> bytes:
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Dekrety"
        sheet.append([label for _, label in COLUMNS])
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        money_columns = {
            index + 1
            for index, (name, _) in enumerate(COLUMNS)
            if name in ("debit", "credit")
        }
        date_columns = {
            index + 1
            for index, (name, _) in enumerate(COLUMNS)
            if name in ("issue_date", "received_date")
        }
        for row in rows:
            sheet.append(safe_row(_values(row)))
            line = sheet.max_row
            for column in money_columns:
                sheet.cell(row=line, column=column).number_format = "#,##0.00"
            for column in date_columns:
                sheet.cell(row=line, column=column).number_format = "yyyy-mm-dd"
        buffer = io.BytesIO()
        workbook.save(buffer)
        return buffer.getvalue()


def _csv_cell(value: Any) -> Any:
    if isinstance(value, Decimal):
        return f"{value:.2f}".replace(".", ",")
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

    def render(self, rows: list[ExportRow]) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
        writer.writerow([label for _, label in COLUMNS])
        for row in rows:
            writer.writerow([_csv_cell(value) for value in _values(row)])
        # BOM: polski Excel otwiera wtedy plik w UTF-8.
        return buffer.getvalue().encode("utf-8-sig")


FORMATS: dict[str, ExportFormat] = {
    item.key: item for item in (NeutralXlsx(), NeutralCsv())
}
DEFAULT_FORMAT = NeutralXlsx.key
