"""Excel export shared by legacy and multi-consultant client orders."""

from __future__ import annotations

import io
import re
import unicodedata
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Optional

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter


@dataclass(frozen=True)
class OrderExportRow:
    consultant_name: str
    order_number: str
    cost_rate: Optional[Decimal]
    revenue_rate: Optional[Decimal]
    start_date: Optional[date]
    end_date: Optional[date]
    allocation: Optional[Decimal] = None
    consumption: Optional[Decimal] = None


BASE_HEADERS = (
    "Imię i nazwisko",
    "Numer zamówienia",
    "Stawka kosztowa",
    "Stawka przychodowa",
    "Okres zamówienia",
)
MODEL_HEADERS = ("Liczba MD / Kwota zamówienia", "Zużycie zamówienia")


def _safe_text(value: str) -> str:
    """Prevent user-controlled text from becoming an Excel formula."""

    return f"'{value}" if value.startswith(("=", "+", "-", "@")) else value


def _period(row: OrderExportRow) -> str:
    start = row.start_date.strftime("%d.%m.%Y") if row.start_date else "—"
    end = row.end_date.strftime("%d.%m.%Y") if row.end_date else "bezterminowo"
    return f"{start} – {end}"


def build_orders_workbook(
    rows: list[OrderExportRow], *, include_model_columns: bool
) -> bytes:
    """Build a readable, typed .xlsx workbook entirely in memory."""

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Zamówienia"
    headers = [*BASE_HEADERS, *(MODEL_HEADERS if include_model_columns else ())]
    sheet.append(headers)

    header_fill = PatternFill("solid", fgColor="1F4E78")
    for cell in sheet[1]:
        cell.font = Font(color="FFFFFF", bold=True)
        cell.fill = header_fill
        cell.alignment = Alignment(vertical="center")

    for item in rows:
        values: list[object] = [
            _safe_text(item.consultant_name),
            _safe_text(item.order_number),
            item.cost_rate,
            item.revenue_rate,
            _period(item),
        ]
        if include_model_columns:
            values.extend([item.allocation, item.consumption])
        sheet.append(values)

    for row in sheet.iter_rows(min_row=2):
        for column in (3, 4):
            if row[column - 1].value is not None:
                row[column - 1].number_format = "#,##0.###;[Red]-#,##0.###"
        for column in (6, 7):
            if column <= len(row) and row[column - 1].value is not None:
                row[column - 1].number_format = "#,##0.######;[Red]-#,##0.######"

    widths = [30, 20, 19, 21, 27, 31, 24]
    for index, width in enumerate(widths[: len(headers)], start=1):
        sheet.column_dimensions[get_column_letter(index)].width = width
    sheet.freeze_panes = "A2"
    sheet.auto_filter.ref = sheet.dimensions
    sheet.sheet_view.showGridLines = False

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def orders_export_filename(
    client_name: str, generated_on: Optional[date] = None
) -> str:
    """Return the stable ASCII filename required by the product ticket."""

    normalized = unicodedata.normalize("NFKD", client_name)
    ascii_name = normalized.encode("ascii", "ignore").decode("ascii")
    safe_name = re.sub(r"[^A-Za-z0-9]+", "_", ascii_name).strip("_") or "Klient"
    stamp = (generated_on or date.today()).strftime("%d.%m.%Y")
    return f"Zamowienia_{safe_name}_{stamp}.xlsx"
