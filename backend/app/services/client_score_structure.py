"""Tabela punktowa klienta: odczyt pól do wypełnienia z wzoru XLSX. Bez AI, bez bazy.

Centrum e-Zdrowia do formularza CV ze SWZ dokłada Excel z punktacją według
„Szczegółowego opisu oceny” (zał. 5): dane osoby, tabela wymagań „Tak/Nie”
i tabela kryteriów punktowanych z „Liczbą punktów” (maksimum) i kolumną na
wynik. Decyzja Artura 27.10.2026: NEXUS wypełnia ten Excel jak formularz —
jeden na osobę (``docs/claude/generator-cv/formularz-klienta-zamiast-cv-firmowego.md``).

Ten moduł raz odczytuje strukturę wzoru, w tym samym kształcie co
``client_form_structure`` (pola ``line`` i ``cell``), więc wypełnianie
(``client_form_fill``) i okno braków działają bez zmian:

* ``line`` — komórka zaraz za etykietą z dwukropkiem („Imię i nazwisko:”),
* ``cell`` — pusta komórka (albo podpowiedź „Tak/Nie”) w wierszu tabeli pod
  nagłówkiem z „Lp.”; etykieta = nagłówek kolumny, nazwa wiersza = oceniany
  element. Gdy wiersz ma liczbę w kolumnie „punkty”, pole niesie
  ``max_points`` — wynik nie może go przekroczyć.

Wiersze „Razem” i komórki z formułą zostają nietknięte — Excel sam liczy sumy.
Identyfikator pola ``s0.r13.c4`` = arkusz, wiersz, kolumna (jak w Excelu, od 1).
"""

from __future__ import annotations

import io
import re
import zipfile
from typing import Any, Optional

from openpyxl import load_workbook
from openpyxl.cell.cell import MergedCell

from app.services.client_form_structure import FormRejected, summary

STRUCTURE_VERSION = 1

MAX_ZIP_ENTRIES = 1000
MAX_UNPACKED_BYTES = 60 * 1024 * 1024
MAX_SHEETS = 10
MAX_ROWS = 300
MAX_COLS = 30
MIN_FIELDS = 3
MAX_LABEL_CHARS = 120

MSG_NOT_XLSX = "Tabela punktowa musi być plikiem Excel (.xlsx)."
MSG_BROKEN = "Nie da się odczytać pliku Excel — zapisz go w Excelu od nowa."
MSG_TOO_BIG = "Plik Excel po rozpakowaniu jest za duży."
MSG_MACROS = "Plik z makrami nie może być wzorem — zapisz go jako zwykły .xlsx."
MSG_NO_FORM = (
    "W tym arkuszu nie ma pustych pól do wypełnienia — NEXUS nie rozpoznał w nim "
    "tabeli punktowej."
)

_LP = re.compile(r"^\s*l\.?\s*p\.?\s*$", re.IGNORECASE)
_ORDINAL = re.compile(r"^\s*\d{1,3}\s*\.?\s*$")
_TOTAL = re.compile(r"^\s*(razem|suma|łącznie)\b", re.IGNORECASE)
_YES_NO_HINT = re.compile(r"^\s*tak\s*/\s*nie\s*$", re.IGNORECASE)
_POINTS_HEADER = re.compile(r"punkt|maks", re.IGNORECASE)
_ELEMENT_HEADER = re.compile(
    r"element|kompetenc|nazwa|wymagan|kryter|opis", re.IGNORECASE
)


def _clean(value: Any) -> str:
    return " ".join(str(value).split()) if value is not None else ""


def _label(text: str) -> str:
    return _clean(text).rstrip(":").rstrip("*").strip()[:MAX_LABEL_CHARS]


def _is_formula(value: Any) -> bool:
    return isinstance(value, str) and value.startswith("=")


def _check_package(content: bytes) -> None:
    try:
        package = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise FormRejected(MSG_NOT_XLSX) from exc
    with package:
        entries = package.infolist()
        if len(entries) > MAX_ZIP_ENTRIES:
            raise FormRejected(MSG_BROKEN)
        if sum(entry.file_size for entry in entries) > MAX_UNPACKED_BYTES:
            raise FormRejected(MSG_TOO_BIG)
        names = {entry.filename.lower() for entry in entries}
        if "xl/workbook.xml" not in names:
            raise FormRejected(MSG_NOT_XLSX)
        if any(name.endswith("vbaproject.bin") for name in names):
            raise FormRejected(MSG_MACROS)


def open_workbook(content: bytes) -> Any:
    """Skoroszyt openpyxl po kontroli paczki; odmowa = ``FormRejected``."""
    _check_package(content)
    try:
        return load_workbook(io.BytesIO(content), data_only=False)
    except Exception as exc:  # uszkodzony XLSX (openpyxl, zipfile, XML)
        raise FormRejected(MSG_BROKEN) from exc


def _row_values(sheet: Any, row: int, width: int) -> list[tuple[int, Any]]:
    """(kolumna, wartość) wiersza — tylko komórki z treścią lub kotwice scaleń."""
    out: list[tuple[int, Any]] = []
    for column in range(1, width + 1):
        cell = sheet.cell(row=row, column=column)
        if isinstance(cell, MergedCell):
            continue
        out.append((column, cell.value))
    return out


def _points(value: Any) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and value >= 0:
        return int(value)
    text = _clean(value)
    return int(text) if text.isdigit() else None


def _sheet_fields(
    sheet: Any, s_index: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    fields: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    height = min(sheet.max_row or 0, MAX_ROWS)
    width = min(sheet.max_column or 0, MAX_COLS)
    headers: dict[int, str] = {}
    points_col: Optional[int] = None
    element_col: Optional[int] = None
    section: Optional[str] = None
    table: Optional[dict[str, Any]] = None

    for row in range(1, height + 1):
        cells = _row_values(sheet, row, width)
        texts = {col: _clean(value) for col, value in cells if _clean(value)}
        if not texts:
            table = None if table is not None and table["rows"] else table
            continue

        # Nagłówek tabeli: „Lp.” i co najmniej jeszcze jedna kolumna.
        if any(_LP.match(text) for text in texts.values()) and len(texts) >= 2:
            headers = {col: _label(text) for col, text in texts.items()}
            points_col = next(
                (col for col, text in headers.items() if _POINTS_HEADER.search(text)),
                None,
            )
            element_col = next(
                (col for col, text in headers.items() if _ELEMENT_HEADER.search(text)),
                next(
                    (col for col, text in headers.items() if not _LP.match(text)), None
                ),
            )
            table = {
                "index": len(tables),
                "title": section,
                "rows": 0,
                "extendable": False,
            }
            tables.append(table)
            continue

        # Etykieta z dwukropkiem i pusta komórka za nią („Imię i nazwisko:”).
        if len(texts) == 1:
            ((col, text),) = texts.items()
            if text.endswith(":") and len(text) <= MAX_LABEL_CHARS:
                target = next(
                    (c for c, value in cells if c > col and not _clean(value)), None
                )
                if target is not None and target <= col + 3:
                    fields.append(
                        {
                            "id": f"s{s_index}.r{row}.c{target}",
                            "kind": "line",
                            "label": _label(text),
                            "section": None,
                            "row_label": None,
                            "table": None,
                        }
                    )
                    continue
            # Wiersz z jednym tekstem to sekcja („Wymagania obligatoryjne”),
            # także wewnątrz tabeli — wiersze danych mają numer albo punkty.
            section = _label(text)
            continue

        if table is None or not headers:
            continue
        element = texts.get(element_col) if element_col is not None else None
        if not element or _TOTAL.match(element) or _ORDINAL.match(element):
            continue
        max_points = _points(dict(cells).get(points_col)) if points_col else None
        hints = {col for col, value in cells if _YES_NO_HINT.match(_clean(value))}
        empty = [
            col
            for col, value in cells
            if not _clean(value)
            and not _is_formula(value)
            and headers.get(col)
            and not _LP.match(headers[col])
            and col not in (element_col, points_col)
        ]
        # „Tak/Nie” w wierszu to metoda oceny (zał. 5), odpowiedź idzie do
        # pustej kolumny obok („Wynik”); bez pustej kolumny polem jest sama
        # komórka z podpowiedzią.
        targets = empty or sorted(hints)
        added = 0
        for col in targets:
            header = headers[col]
            if hints:
                label = header if _YES_NO_HINT.match(header) else f"{header} (Tak/Nie)"
            elif max_points is not None:
                label = f"{header} (0–{max_points} pkt)"
            else:
                label = header
            field: dict[str, Any] = {
                "id": f"s{s_index}.r{row}.c{col}",
                "kind": "cell",
                "label": label,
                "section": section,
                "row_label": _label(element),
                "table": table["title"] or sheet.title,
            }
            if max_points is not None and not hints:
                field["max_points"] = max_points
            fields.append(field)
            added += 1
        if added:
            table["rows"] += 1
    return fields, [item for item in tables if item["rows"]]


def read_structure(content: bytes) -> dict[str, Any]:
    """Pola tabeli punktowej albo ``FormRejected`` ze zdaniem dla użytkownika."""
    workbook = open_workbook(content)
    fields: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    sheets = [sheet for sheet in workbook.worksheets if sheet.sheet_state == "visible"]
    for s_index, sheet in enumerate(workbook.worksheets[:MAX_SHEETS]):
        if sheet not in sheets:
            continue
        sheet_fields, sheet_tables = _sheet_fields(sheet, s_index)
        offset = len(tables)
        for table in sheet_tables:
            table["index"] += offset
        fields.extend(sheet_fields)
        tables.extend(sheet_tables)
    if len(fields) < MIN_FIELDS or not any(item["kind"] == "cell" for item in fields):
        raise FormRejected(MSG_NO_FORM)
    return {
        "version": STRUCTURE_VERSION,
        "format": "xlsx",
        "fields": fields,
        "tables": tables,
    }


def max_points_total(structure: dict[str, Any]) -> int:
    return sum(
        int(item.get("max_points") or 0) for item in structure.get("fields") or []
    )


__all__ = [
    "MSG_NOT_XLSX",
    "MSG_NO_FORM",
    "STRUCTURE_VERSION",
    "max_points_total",
    "open_workbook",
    "read_structure",
    "summary",
]
