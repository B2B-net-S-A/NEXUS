"""Odczyt Time Sheet konsultanta w godzinach (roadmapa E6.2) i kontrole. Bez bazy.

Szablon „Time Sheet” (XLSX): nagłówek „Project Name”, „Consultant(s)”,
„Date from”, „Date to”, potem tabela „Date · Project · Description · Total
Hours · Billable · Non-billable · Nr strumienia” zakończona wierszem „Total
Hours”. Konsultant bywa kopiuje tabelę na kilka tygodni albo arkuszy, więc
czytamy każdą tabelę z każdego widocznego arkusza.

Godziny do rozliczenia to „Billable”; bez tej kolumny „Total Hours” minus
„Non-billable”. MD = godziny / ``fields.md_hours`` (domyślnie 8 h). Jedna osoba
może mieć kilka projektów: projekt bierzemy z wiersza, a bez niego z nagłówka.
„Nr strumienia” (albo „Task ID”) trafia do potwierdzenia usług klienta jako
Task ID (odpowiedź rozliczeń z 12.11.2026: „cokolwiek z TS-a konsultanta”).

Plik spoza szablonu daje ``None``: wtedy MD wpisują Finanse, a plik zostaje.
Odczyt nigdy nie blokuje przyjęcia pliku.
"""

from __future__ import annotations

import io
import logging
import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Optional

from app.services.client_settlements.rcp_bnp import _dec
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
GROUP_TITLE = "Time Sheet"
MD_Q = Decimal("0.001")
TOLERANCE = Decimal("0.01")
NO_PROJECT = "Bez projektu"
MAX_ROWS = 400
MAX_COLS = 20

_HEADER_LABELS = {
    "project name": "project_name",
    "consultant(s)": "consultant",
    "consultant": "consultant",
    "date from": "date_from",
    "date to": "date_to",
}
_COLUMNS = {
    "date": "date",
    "project": "project",
    "description": "description",
    "total hours": "total",
    "billable": "billable",
    "non-billable": "non_billable",
    "nr strumienia": "task_id",
    "task id": "task_id",
}


@dataclass(frozen=True)
class TsEntry:
    day: Optional[date]
    project: Optional[str]
    description: str
    hours: Decimal
    task_id: Optional[str]


@dataclass(frozen=True)
class ParsedTimesheet:
    project_name: Optional[str]
    consultant: Optional[str]
    date_from: Optional[date]
    date_to: Optional[date]
    entries: tuple[TsEntry, ...]
    #: Suma z wierszy „Total Hours” szablonu (``None``, gdy pusta albo bez wzoru).
    declared_total: Optional[Decimal]

    @property
    def total_hours(self) -> Decimal:
        return sum((e.hours for e in self.entries), Decimal("0"))

    @property
    def month(self) -> Optional[str]:
        """Miesiąc z „Date from”, bez niego najczęstszy miesiąc wpisów."""

        if self.date_from is not None:
            return f"{self.date_from.year}-{self.date_from.month:02d}"
        counts: dict[str, int] = defaultdict(int)
        for entry in self.entries:
            if entry.day is not None:
                counts[f"{entry.day.year}-{entry.day.month:02d}"] += 1
        return max(counts, key=lambda m: counts[m]) if counts else None

    def project_of(self, entry: TsEntry) -> str:
        return entry.project or self.project_name or NO_PROJECT

    def hours_by_project(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for entry in self.entries:
            key = self.project_of(entry)
            out[key] = out.get(key, Decimal("0")) + entry.hours
        return out

    def day_totals(self) -> dict[date, Decimal]:
        out: dict[date, Decimal] = defaultdict(lambda: Decimal("0"))
        for entry in self.entries:
            if entry.day is not None:
                out[entry.day] += entry.hours
        return dict(out)


def _label(cell: Any) -> Optional[str]:
    if not isinstance(cell, str):
        return None
    text = " ".join(cell.split()).strip().rstrip(":").lower()
    return text or None


def _text(cell: Any) -> Optional[str]:
    if cell is None:
        return None
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    text = " ".join(str(cell).split())
    return text or None


def _day(cell: Any) -> Optional[date]:
    if isinstance(cell, datetime):
        return cell.date()
    if isinstance(cell, date):
        return cell
    text = str(cell or "").strip()
    match = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})(?:[ T].*)?", text)
    if match:
        year, mon, day = (int(x) for x in match.groups())
    else:
        match = re.fullmatch(r"(\d{1,2})[./](\d{1,2})[./](\d{4})", text)
        if not match:
            return None
        day, mon, year = (int(x) for x in match.groups())
    try:
        return date(year, mon, day)
    except ValueError:
        return None


def _after(row: list[Any], index: int) -> Any:
    return next((v for v in row[index + 1 :] if v not in (None, "")), None)


def _header_columns(row: list[Any]) -> Optional[dict[str, int]]:
    labels = [_label(c) for c in row]
    if "date" not in labels or not any(
        label and label.startswith("total hours") for label in labels
    ):
        return None
    columns: dict[str, int] = {}
    for i, label in enumerate(labels):
        if label is None:
            continue
        key = _COLUMNS.get(label)
        if key is None and label.startswith("total hours"):
            key = "total"
        if key is not None and key not in columns:
            columns[key] = i
    return columns


def _cell(row: list[Any], columns: Mapping[str, int], key: str) -> Any:
    index = columns.get(key)
    return row[index] if index is not None and index < len(row) else None


def parse_rows(sheets: Iterable[list[list[Any]]]) -> Optional[ParsedTimesheet]:
    """Wiersze arkuszy → Time Sheet. Wydzielone, żeby testy nie wymagały XLSX."""

    header: dict[str, Any] = {}
    entries: list[TsEntry] = []
    declared: Optional[Decimal] = None
    found_table = False
    for rows in sheets:
        columns: Optional[dict[str, int]] = None
        for row in rows:
            for i, cell in enumerate(row):
                key = _HEADER_LABELS.get(_label(cell) or "")
                if key and key not in header:
                    value = _after(row, i)
                    if value is not None:
                        header[key] = value
            new_columns = _header_columns(row)
            if new_columns is not None:
                columns, found_table = new_columns, True
                continue
            if columns is None:
                continue
            labels = [_label(c) or "" for c in row]
            total_at = next(
                (
                    i
                    for i, label in enumerate(labels)
                    if label.startswith("total hours")
                ),
                None,
            )
            if total_at is not None:
                value = _dec(_after(row, total_at))
                if value is not None:
                    declared = (declared or Decimal("0")) + value
                columns = None
                continue
            description = _text(_cell(row, columns, "description"))
            billable = _dec(_cell(row, columns, "billable"))
            total = _dec(_cell(row, columns, "total"))
            non_billable = _dec(_cell(row, columns, "non_billable")) or Decimal("0")
            if billable is None and "billable" in columns and total is None:
                continue
            hours = (
                billable
                if billable is not None
                else (total - non_billable if total is not None else None)
            )
            if hours is None or hours <= 0:
                continue
            entries.append(
                TsEntry(
                    day=_day(_cell(row, columns, "date")),
                    project=_text(_cell(row, columns, "project")),
                    description=description or "",
                    hours=hours,
                    task_id=_text(_cell(row, columns, "task_id")),
                )
            )
    if not found_table:
        return None
    return ParsedTimesheet(
        project_name=_text(header.get("project_name")),
        consultant=_text(header.get("consultant")),
        date_from=_day(header.get("date_from")),
        date_to=_day(header.get("date_to")),
        entries=tuple(entries),
        declared_total=declared,
    )


def _sheets(content: bytes) -> Optional[list[list[list[Any]]]]:
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), data_only=True, read_only=True
        )
    except Exception as exc:  # noqa: BLE001
        logger.info("timesheet: XLSX nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        return [
            [
                list(row)
                for row in ws.iter_rows(
                    max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
                )
            ]
            for ws in workbook.worksheets
            if ws.sheet_state == "visible"
        ]
    finally:
        workbook.close()


def parse(content: bytes, mime: str) -> Optional[ParsedTimesheet]:
    if mime != XLSX:
        return None
    sheets = _sheets(content)
    return parse_rows(sheets) if sheets is not None else None


def md_from_hours(hours: Decimal, per_md: Decimal) -> Decimal:
    return (hours / per_md).quantize(MD_Q, rounding=ROUND_HALF_UP)


def per_md(rules: Mapping[str, Mapping[str, Any]]) -> Decimal:
    value = _param_dec(rules, "fields.md_hours", "hours", "8")
    return value if value > 0 else Decimal("8")


def evaluate(
    parsed: ParsedTimesheet,
    *,
    month: str,
    person_name: str,
    has_mail: bool,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
) -> ProofResult:
    """Kontrole Time Sheet z katalogu reguł; MD z godzin, bez pracy dodatkowej."""

    result = ProofResult(md_regular=None, md_extra=None)
    sheet = _Group(result, rules, GROUP_TITLE)
    hours = parsed.total_hours
    hours_md = per_md(rules)

    if not parsed.entries:
        sheet.info(
            "Time Sheet bez godzin",
            "Nie ma wierszy z godzinami. MD wpisują Finanse; plik zostaje w NEXUS-ie.",
        )
        result.warn = True
        sheet.close()
        return result

    result.md_regular = md_from_hours(hours, hours_md)
    result.md_extra = Decimal("0")

    if parsed.month == month:
        sheet.ok(f"Miesiąc z Time Sheet: {month}")
    else:
        sheet.fail(
            "proof.month",
            "Time Sheet za inny miesiąc",
            f"W pliku: {parsed.month or 'brak dat'}.",
        )
    outside = sum(
        1
        for e in parsed.entries
        if e.day is not None and f"{e.day.year}-{e.day.month:02d}" != month
    )
    if outside:
        sheet.fail(
            "proof.month",
            f"Wpisy spoza rozliczanego miesiąca: {outside}",
            "Godziny z tych wierszy są w sumie; sprawdź daty.",
        )

    consultant = name_tokens(parsed.consultant)
    person = name_tokens(person_name)
    if consultant and person and (consultant <= person or person <= consultant):
        sheet.ok("Imię i nazwisko jak w kontrakcie")
    elif consultant:
        sheet.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    else:
        sheet.fail("proof.name_match", "Time Sheet bez pola Consultant(s)")

    if sheet.on("proof.excel_with_mail"):
        if has_mail:
            sheet.ok("Mail z akceptacją godzin jest")
        else:
            sheet.fail(
                "proof.excel_with_mail",
                "Brak maila z akceptacją godzin",
                "Dołącz mail z akceptacją (MSG, EML albo PDF z wydrukiem).",
            )

    projects = parsed.hours_by_project()
    sheet.info(
        "Projekty: "
        + ", ".join(f"{name} {_fmt(value)} h" for name, value in projects.items()),
        None
        if len(projects) == 1
        else "Potwierdzenie usług powstaje osobno na każdy projekt.",
    )
    sheet.close()

    sums = _Group(result, rules, "Pola i sumy")
    if sums.on("fields.md_hours"):
        detail = f"{_fmt(hours)} h / {_fmt(hours_md)} = {_fmt(result.md_regular)} MD."
        if parsed.declared_total is not None and (
            abs(parsed.declared_total - hours) > TOLERANCE
        ):
            sums.fail(
                "fields.md_hours",
                "Suma „Total Hours” inna niż suma wierszy",
                f"W pliku {_fmt(parsed.declared_total)} h, z wierszy {_fmt(hours)} h. {detail}",
            )
        else:
            sums.ok("Godziny policzone od nowa", detail)
    days = parsed.day_totals()
    if sums.on("fields.day_limit") and days:
        limit = _param_dec(rules, "fields.day_limit", "hours", "24")
        worst_day = max(days, key=lambda d: days[d])
        if days[worst_day] <= limit:
            sums.ok(
                f"Najwięcej w jednym dniu: {_fmt(days[worst_day])} h",
                f"Limit {_fmt(limit)} h.",
            )
        else:
            sums.fail(
                "fields.day_limit",
                f"{_fmt(days[worst_day])} h w dniu {worst_day.strftime('%d.%m')}",
                f"Limit {_fmt(limit)} h.",
            )
    if sums.on("fields.md_month_limit") and working_days > 0:
        if result.md_regular <= working_days:
            sums.ok(
                f"{_fmt(result.md_regular)} MD przy {working_days} dniach roboczych"
            )
        else:
            sums.fail(
                "fields.md_month_limit",
                f"{_fmt(result.md_regular)} MD przy {working_days} dniach roboczych",
                "Więcej MD niż dni roboczych: sprawdź, czy godziny nie są za dwóch klientów.",
            )
    sums.close()
    return result
