"""Odczyt raportu godzin Time for Teams (T4T) od Cost Control Nordei (plan N1.2). Bez bazy.

Arkusz raportu rozpoznajemy po kolumnach (``Investment ID`` … ``TimesheetStatus``),
nie po nazwie: Cost Control przysyła „Sheet1”, a Finanse składają kolejne
wersje w jednym pliku jako „Sheet1 (2)”, „Sheet1 (3)” obok własnych tabel
przestawnych. Plik z kilkoma arkuszami raportu wymaga wskazania arkusza.

Wiersz raportu: osoba (``UserId``, ``Name``), NIDS (``Investment ID``), okres
T4T (``TimePeriodStart`` – ``TimePeriodFinish``), dzień, godziny i status
(0 Not submitted, 1 Submitted, 2 Approved, 3 Rejected).
"""

from __future__ import annotations

import io
import logging
import zipfile
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

logger = logging.getLogger(__name__)

HEADER_SCAN_ROWS = 10
MAX_ROWS = 50_000
STATUSES = (0, 1, 2, 3)

#: Kolumna w pliku → pole wiersza. Wymagane bez nich wiersza nie da się użyć.
COLUMNS = {
    "investment id": "project_no",
    "name": "person_name",
    "userid": "person_no",
    "timeperiodstart": "period_start",
    "timeperiodfinish": "period_end",
    "dateworked": "work_date",
    "investment name": "project_name",
    "sum of hours": "hours",
    "timesheetstatus": "status",
    "chargecode": "charge_code",
    "externalcompanyname": "company",
}
REQUIRED = (
    "project_no",
    "person_no",
    "period_start",
    "period_end",
    "hours",
    "status",
)


class T4tError(ValueError):
    """Plik nie jest raportem T4T albo nie da się go użyć; komunikat dla Finansów."""


@dataclass(frozen=True)
class T4tRow:
    person_no: str
    person_name: Optional[str]
    project_no: Optional[str]
    project_name: Optional[str]
    period_start: date
    period_end: date
    work_date: Optional[date]
    hours: Decimal
    status: int
    charge_code: Optional[str]
    company: Optional[str]


@dataclass(frozen=True)
class T4tSheet:
    name: str
    rows: tuple[T4tRow, ...]
    skipped: int

    @property
    def month(self) -> Optional[str]:
        """Miesiąc raportu: najczęstszy miesiąc początku okresu."""

        counts = Counter(f"{r.period_start:%Y-%m}" for r in self.rows)
        return counts.most_common(1)[0][0] if counts else None


def _key(value: Any) -> str:
    return " ".join(str(value or "").split()).lower()


def _text(value: Any, limit: int) -> Optional[str]:
    text = " ".join(str(value).split()) if value is not None else ""
    return text[:limit] or None


def _day(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        text = value.strip()[:10]
        for fmt in ("%Y-%m-%d", "%d.%m.%Y"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    return None


def _hours(value: Any) -> Optional[Decimal]:
    if value is None or isinstance(value, bool):
        return None
    try:
        hours = Decimal(str(value).replace(",", ".").strip())
    except InvalidOperation:
        return None
    return hours if hours.is_finite() else None


def _status(value: Any) -> Optional[int]:
    try:
        status = int(Decimal(str(value).strip()))
    except (InvalidOperation, ValueError):
        return None
    return status if status in STATUSES else None


def _header(cells: tuple[Any, ...]) -> Optional[dict[str, int]]:
    found = {
        COLUMNS[_key(cell)]: index
        for index, cell in enumerate(cells)
        if _key(cell) in COLUMNS
    }
    return found if all(field in found for field in REQUIRED) else None


def _row(cells: tuple[Any, ...], cols: dict[str, int]) -> Optional[T4tRow]:
    def cell(field: str) -> Any:
        index = cols.get(field)
        return cells[index] if index is not None and index < len(cells) else None

    person_no = _text(cell("person_no"), 32)
    start, end = _day(cell("period_start")), _day(cell("period_end"))
    hours, status = _hours(cell("hours")), _status(cell("status"))
    if not person_no or start is None or end is None or hours is None:
        return None
    if status is None:
        return None
    return T4tRow(
        person_no=person_no.upper(),
        person_name=_text(cell("person_name"), 255),
        project_no=_text(cell("project_no"), 32),
        project_name=_text(cell("project_name"), 255),
        period_start=start,
        period_end=end,
        work_date=_day(cell("work_date")),
        hours=hours,
        status=status,
        charge_code=_text(cell("charge_code"), 64),
        company=_text(cell("company"), 128),
    )


def _read_sheet(worksheet: Any) -> Optional[T4tSheet]:
    cols: Optional[dict[str, int]] = None
    rows: list[T4tRow] = []
    skipped = 0
    for index, cells in enumerate(worksheet.iter_rows(values_only=True)):
        if cols is None:
            if index >= HEADER_SCAN_ROWS:
                return None
            cols = _header(cells)
            continue
        if not any(c is not None and str(c).strip() for c in cells):
            continue
        if len(rows) >= MAX_ROWS:
            raise T4tError(
                f"Arkusz „{worksheet.title}” ma więcej niż {MAX_ROWS} wierszy."
            )
        row = _row(cells, cols)
        if row is None:
            skipped += 1
        else:
            rows.append(row)
    if cols is None:
        return None
    return T4tSheet(worksheet.title, tuple(rows), skipped)


def read(content: bytes) -> list[T4tSheet]:
    """Wszystkie arkusze raportu T4T w pliku, w kolejności arkuszy."""

    import openpyxl
    from openpyxl.utils.exceptions import InvalidFileException

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
    except (
        InvalidFileException,
        zipfile.BadZipFile,
        KeyError,
        OSError,
        ValueError,
    ) as exc:
        raise T4tError("To nie jest plik Excel (XLSX).") from exc
    try:
        sheets = [s for s in map(_read_sheet, workbook.worksheets) if s is not None]
    finally:
        workbook.close()
    if not sheets:
        raise T4tError(
            "W pliku nie ma arkusza raportu T4T (kolumny Investment ID, UserId, "
            "TimePeriodStart, TimePeriodFinish, Sum of Hours, TimesheetStatus)."
        )
    return sheets


def pick(sheets: list[T4tSheet], name: Optional[str]) -> T4tSheet:
    """Arkusz do wgrania: jedyny albo wskazany z nazwy."""

    if name:
        for sheet in sheets:
            if sheet.name == name:
                return sheet
        raise T4tError(f"W pliku nie ma arkusza raportu „{name}”.")
    if len(sheets) > 1:
        raise T4tError("W pliku jest kilka arkuszy raportu T4T — wybierz arkusz.")
    return sheets[0]
