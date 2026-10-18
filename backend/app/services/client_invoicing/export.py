"""Eksport pozycji „do faktury” (CSV, XLSX) do systemu, w którym wystawia się faktury.

Jeden wiersz = pozycja jednej osoby (albo puli MD) w zamówieniu. Pozycja bez
kwoty (np. brak zużycia MD) też jest w pliku — z pustą kwotą i uwagą, żeby
plik nie wyglądał na komplet, gdy nim nie jest. Stawki VAT NEXUS nie zna —
kolumny nie ma. Komórki zaczynające się od ``=``, ``+``, ``-``, ``@`` są
neutralizowane (``safe_row``), bo plik otwiera się w arkuszu.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from typing import Any

from openpyxl import Workbook

from app.core.export_safety import safe_row
from app.services.client_invoicing.views import KIND_LABELS

COLUMNS: tuple[str, ...] = (
    "Klient",
    "NIP klienta",
    "Miesiąc usługi",
    "Zamówienie",
    "Rodzaj",
    "Konsultant",
    "Opis pozycji",
    "Ilość",
    "Jednostka",
    "Cena netto",
    "Wartość netto",
    "Waluta",
    "Uwagi",
    "Faktura z KSeF",
)

MONTHS_PL = (
    "styczeń",
    "luty",
    "marzec",
    "kwiecień",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpień",
    "wrzesień",
    "październik",
    "listopad",
    "grudzień",
)


def month_label(period: str) -> str:
    year, month = (int(part) for part in period.split("-", 1))
    return f"{MONTHS_PL[month - 1]} {year}"


def _description(row: dict[str, Any], line: dict[str, Any], period: str) -> str:
    return f"Usługi wg zamówienia {row['order_number']} — {line['consultant']} — {month_label(period)}"


def table(
    rows: Sequence[dict[str, Any]], *, period: str, nips: dict[int, str]
) -> list[list[Any]]:
    """Wiersze pliku z wierszy ``views.month_view`` (kwoty jako tekst z kropką)."""

    out: list[list[Any]] = []
    for row in rows:
        for line in row["lines"]:
            out.append(
                [
                    row.get("client_name") or "",
                    nips.get(row["client_id"], ""),
                    period,
                    row["order_number"],
                    KIND_LABELS.get(row["kind"], row["kind"]),
                    line["consultant"],
                    _description(row, line, period),
                    line["quantity"] or "",
                    line["unit"],
                    line["unit_price"] or "",
                    line["net"] or "",
                    line["currency"],
                    line["note"] or "",
                    row["status_label"],
                ]
            )
    return out


def _decimal_text(value: Any) -> Any:
    """Polski arkusz: przecinek dziesiętny w CSV."""

    if (
        isinstance(value, str)
        and value.replace(".", "", 1).replace("-", "", 1).isdigit()
    ):
        return value.replace(".", ",")
    return value


def to_csv(lines: Sequence[Sequence[Any]]) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(COLUMNS)
    for line in lines:
        writer.writerow(safe_row([_decimal_text(value) for value in line]))
    return ("﻿" + buffer.getvalue()).encode("utf-8")


_NUMERIC = {7, 9, 10}


def to_xlsx(lines: Sequence[Sequence[Any]]) -> bytes:
    book = Workbook()
    sheet = book.active
    sheet.title = "Do faktury"
    sheet.append(list(COLUMNS))
    for line in lines:
        values = safe_row(line)
        for index in _NUMERIC:
            raw = line[index]
            if isinstance(raw, str) and raw:
                try:
                    values[index] = float(raw)
                except ValueError:
                    pass
        sheet.append(values)
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


__all__ = ["COLUMNS", "month_label", "table", "to_csv", "to_xlsx"]
