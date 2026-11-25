"""Zestawienie godzin dostawcy BNP Paribas CIB („Vendor's file”) → MD osoby. Bez bazy.

Próba IX–X 2026. Koordynatorka wysyła klientowi „RRRRMM_<firma>_worksheet.xlsx”
z prośbą o akceptację czasu pracy, a klient odpisuje „Potwierdzam zestawienie”.
Plik ma arkusz „Vendor's file” z nagłówkiem „No. · ID · Service · Year · Month ·
Resource Name (without Polish letters) · Resource Type · Act MD · Act Hours”
i wierszem na osobę. Czytnik poczty zapisuje go z Wysłanych (#3755). Do tej pory
nikt go nie czytał, więc rozliczenie stało bez MD („Czeka na liczbę MD”).

MD to „Act MD” (``declared``). „Act Hours” inne niż MD × godziny w MD daje plik
bez liczby: nie zgadujemy, który zapis jest dobry, MD wpisują Finanse. Osobę
wybieramy po imieniu i nazwisku z kontraktu. Pliku bez tej osoby nie czytamy:
u BNP Paribas CIB kontrola nazwiska jest wyłączona, więc MD innej osoby weszłyby
bez śladu.
"""

from __future__ import annotations

import io
import logging
import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from app.services.client_settlements.declared import Declared
from app.services.client_settlements.mail_text import MONTHS_EN, _month_index
from app.services.client_settlements.rcp_checks import name_tokens

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SOURCE = "Zestawienie godzin dostawcy BNP Paribas CIB"
MAX_ROWS = 200
MAX_COLS = 20
_TOLERANCE = Decimal("0.01")
_COLUMNS = {
    "year": "year",
    "month": "month",
    "act md": "md",
    "act hours": "hours",
}


@dataclass(frozen=True)
class Row:
    person: str
    #: ``RRRR-MM`` z kolumn „Year” i „Month”; ``None``, gdy ich nie da się odczytać.
    month: Optional[str]
    md: Optional[Decimal]
    hours: Optional[Decimal]


def _label(cell: Any) -> str:
    return " ".join(str(cell).split()).lower() if isinstance(cell, str) else ""


#: Liczba z jednostką wpisaną w komórkę: „17,5MD”, „140 h” (próba VI–VIII 2026).
_UNIT = re.compile(r"\s*(?:md|mds|h|godz\.?)\s*$", re.IGNORECASE)


def _number(cell: Any) -> Optional[Decimal]:
    if isinstance(cell, bool) or cell in (None, ""):
        return None
    try:
        return Decimal(_UNIT.sub("", str(cell).strip()).replace(",", "."))
    except InvalidOperation:
        return None


def _month(year: Any, month: Any) -> Optional[str]:
    number = _number(year)
    if number is None or number != number.to_integral() or not 2000 < number < 2100:
        return None
    if isinstance(month, str):
        word = month.strip().lower()
        index = MONTHS_EN.index(word) + 1 if word in MONTHS_EN else _month_index(word)
    else:
        value = _number(month)
        index = (
            int(value) if value is not None and value == value.to_integral() else None
        )
    if index is None or not 1 <= index <= 12:
        return None
    return f"{int(number)}-{index:02d}"


def _header(row: list[Any]) -> Optional[dict[str, int]]:
    """Kolumny z nagłówka „Vendor's file”; inny wiersz = ``None``."""

    labels = [_label(cell) for cell in row]
    person = next(
        (i for i, label in enumerate(labels) if label.startswith("resource name")),
        None,
    )
    found = {
        key: labels.index(label) for label, key in _COLUMNS.items() if label in labels
    }
    if person is None or len(found) != len(_COLUMNS):
        return None
    return {"person": person, **found}


def parse_rows(rows: list[list[Any]]) -> Optional[tuple[Row, ...]]:
    """Wiersze arkusza → osoby z pliku; arkusz bez nagłówka = ``None``."""

    columns: Optional[dict[str, int]] = None
    found: list[Row] = []
    for row in rows:
        if columns is None:
            columns = _header(row)
            continue

        def cell(key: str) -> Any:
            index = columns[key]
            return row[index] if index < len(row) else None

        person = " ".join(str(cell("person") or "").split())
        if len(name_tokens(person)) < 2:
            continue  # pusty wiersz albo suma
        found.append(
            Row(
                person=person,
                month=_month(cell("year"), cell("month")),
                md=_number(cell("md")),
                hours=_number(cell("hours")),
            )
        )
    return tuple(found) if columns is not None and found else None


def parse(content: bytes, mime: str) -> Optional[tuple[Row, ...]]:
    if mime != XLSX:
        return None
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), data_only=True, read_only=True
        )
    except Exception as exc:  # noqa: BLE001 — uszkodzony plik nie blokuje rozliczenia
        logger.info("vendor_file: XLSX nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        for sheet in workbook.worksheets:
            if sheet.sheet_state != "visible":
                continue
            rows = [
                list(row)
                for row in sheet.iter_rows(
                    max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
                )
            ]
            found = parse_rows(rows)
            if found is not None:
                return found
    finally:
        workbook.close()
    return None


def declared_for(
    rows: tuple[Row, ...], person_name: str, per_md: Decimal
) -> Optional[Declared]:
    """MD osoby z kontraktu. Kilka wierszy osoby sumujemy, gdy są za jeden
    miesiąc; dwa miesiące, brak liczby albo godziny niezgodne z MD = bez liczby."""

    wanted = name_tokens(person_name)
    mine = [r for r in rows if wanted and name_tokens(r.person) == wanted]
    if not mine:
        return None
    months = {r.month for r in mine}
    month = next(iter(months)) if len(months) == 1 else None
    md: Optional[Decimal] = None
    hours: Optional[Decimal] = None
    if month is not None and all(
        r.md is not None and r.hours is not None for r in mine
    ):
        md = sum((r.md for r in mine if r.md is not None), Decimal("0"))
        hours = sum((r.hours for r in mine if r.hours is not None), Decimal("0"))
        if abs(md * per_md - hours) > _TOLERANCE:
            md = hours = None
    return Declared(
        source=SOURCE,
        consultant=mine[0].person,
        month=month,
        hours=hours,
        md=md,
    )
