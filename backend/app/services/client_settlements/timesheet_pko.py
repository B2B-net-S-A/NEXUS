"""Odczyt Time Sheet z szablonu klienta rozliczanego godzinami (roadmapa E6.1, PKO).

Szablon w ``.xlsm`` (z makrami). Czytamy zapisane wartości komórek, nigdy nie
uruchamiamy makr. Dwa warianty szablonu z próbek z 13.11.2026:

* wiersz nagłówka tabeli ma „Lp.”, „Numer projektu / formacji”, „Numer zadania
  projektowego…”, „Rezultat…” i „Liczba godzin realizacji usług <miesiąc> <rok>”
  (godziny w jednej kolumnie);
* nowszy: zamiast kolumny godzin „RAZEM <rok> <miesiąc>” i kolumny dni z datami
  (pierwsza data w nagłówku to 1. dzień miesiąca).

Godziny w formacie [GG]:MM (Excel trzyma je jako ułamek doby: 176 h to 7 dni
8:00). Miesiąc bierzemy z widocznego nagłówka. Ten sam miesiąc stoi też
w kolumnie „Miesiąc realizacji usług”, zwykle ukrytej: w próbce za październik
miała „czerwiec”. Rozbieżność daje ostrzeżenie, nigdy odwrotnie (odpowiedź
rozliczeń z 12.11.2026). Tabela kończy się wierszem „Całkowity czas”; to, co
niżej (wiersze „Przykład”), nie jest pracą konsultanta.

Plik spoza szablonu daje ``None``: dalej próbujemy innych odczytów.
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from app.services.client_settlements.mail_text import (
    MONTHS_NOMINATIVE,
    month_label,
)
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM = "application/vnd.ms-excel.sheet.macroEnabled.12"
MIMES = (XLSX, XLSM)
GROUP_TITLE = "Time Sheet"
HOURS_Q = Decimal("0.01")
MD_Q = Decimal("0.001")
TOLERANCE = Decimal("0.01")
MAX_ROWS = 200
MAX_COLS = 60

_HEADER_FIELDS = {
    "nazwa firmy": "company",
    "nazwisko i imię kontraktora": "consultant",
    "imię i nazwisko kontraktora": "consultant",
    "nr pz": "pz",
    "koordynator odbierający usługę (z banku)": "coordinator",
    "opiekun kontraktora": "coordinator",
    "akceptujący timesheet (z banku)": "approver",
}
_MONTH_NAME = re.compile(
    r"("
    + "|".join(MONTHS_NOMINATIVE)
    + r")\s+(20\d{2})|(20\d{2})\s+("
    + "|".join(MONTHS_NOMINATIVE)
    + r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PkoEntry:
    project: Optional[str]
    task: Optional[str]
    description: str
    hours: Decimal
    days: tuple[tuple[date, Decimal], ...] = ()


@dataclass(frozen=True)
class ParsedPko:
    consultant: Optional[str]
    pz: Optional[str]
    coordinator: Optional[str]
    #: Miesiąc z widocznego nagłówka tabeli (``RRRR-MM``).
    month: Optional[str]
    #: Wartości kolumny „Miesiąc realizacji usług” z wierszy z godzinami.
    month_column: tuple[str, ...]
    month_column_hidden: bool
    entries: tuple[PkoEntry, ...]
    declared_total: Optional[Decimal]
    header_row: int
    columns_hidden: tuple[str, ...] = field(default=())

    @property
    def total_hours(self) -> Decimal:
        return sum((e.hours for e in self.entries), Decimal("0"))

    def day_totals(self) -> dict[date, Decimal]:
        out: dict[date, Decimal] = {}
        for entry in self.entries:
            for day, hours in entry.days:
                out[day] = out.get(day, Decimal("0")) + hours
        return out

    def hours_by_project(self) -> dict[str, Decimal]:
        out: dict[str, Decimal] = {}
        for entry in self.entries:
            key = entry.project or "Bez projektu"
            out[key] = out.get(key, Decimal("0")) + entry.hours
        return out


def _label(cell: Any) -> str:
    return (
        " ".join(str(cell).split()).strip().rstrip(":").lower()
        if isinstance(cell, str)
        else ""
    )


def _text(cell: Any) -> Optional[str]:
    if cell is None:
        return None
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    text = " ".join(str(cell).split())
    return text or None


def duration_hours(cell: Any) -> Optional[Decimal]:
    """Czas z komórki: [GG]:MM (timedelta), czas dnia, tekst „4:0” albo liczba godzin."""

    if cell is None or cell == "":
        return None
    if isinstance(cell, timedelta):
        seconds = Decimal(int(cell.total_seconds()))
        return (seconds / 3600).quantize(HOURS_Q, rounding=ROUND_HALF_UP)
    if isinstance(cell, time):
        return (Decimal(cell.hour) + Decimal(cell.minute) / 60).quantize(HOURS_Q)
    if isinstance(cell, datetime):
        return None
    if isinstance(cell, (int, float, Decimal)) and not isinstance(cell, bool):
        return Decimal(str(cell)).quantize(HOURS_Q, rounding=ROUND_HALF_UP)
    text = str(cell).strip()
    match = re.fullmatch(r"(\d{1,3}):(\d{1,2})(?::\d{1,2})?", text)
    if match:
        return (Decimal(match.group(1)) + Decimal(match.group(2)) / 60).quantize(
            HOURS_Q, rounding=ROUND_HALF_UP
        )
    try:
        return Decimal(text.replace(",", ".")).quantize(HOURS_Q, rounding=ROUND_HALF_UP)
    except InvalidOperation:
        return None


def _month_from_text(text: str) -> Optional[str]:
    match = _MONTH_NAME.search(text)
    if not match:
        return None
    name = (match.group(1) or match.group(4)).lower()
    year = match.group(2) or match.group(3)
    return f"{year}-{MONTHS_NOMINATIVE.index(name) + 1:02d}"


def _month_of(cell: Any) -> Optional[str]:
    """Wartość kolumny miesiąca: data, numer seryjny Excela albo nazwa miesiąca."""

    if isinstance(cell, (datetime, date)):
        return f"{cell.year}-{cell.month:02d}"
    if (
        isinstance(cell, (int, float))
        and not isinstance(cell, bool)
        and 20000 < cell < 80000
    ):
        day = date(1899, 12, 30) + timedelta(days=int(cell))
        return f"{day.year}-{day.month:02d}"
    if isinstance(cell, str):
        text = cell.strip().lower()
        full = _month_from_text(text)
        if full:
            return full
        for index, name in enumerate(MONTHS_NOMINATIVE):
            if text.startswith(name[:4]):
                return f"????-{index + 1:02d}"
    return None


def _column_letter(index: int) -> str:
    from openpyxl.utils import get_column_letter

    return get_column_letter(index + 1)


def parse_rows(
    rows: Iterable[list[Any]], hidden_columns: Iterable[str] = ()
) -> Optional[ParsedPko]:
    """Wiersze arkusza → Time Sheet. Wydzielone, żeby testy nie wymagały pliku."""

    header: dict[str, str] = {}
    table: list[list[Any]] = [list(r) for r in rows]
    hidden = set(hidden_columns)
    header_at = None
    for index, row in enumerate(table):
        labels = [_label(c) for c in row]
        if "lp." in labels and any(
            label.startswith("numer projektu") for label in labels
        ):
            header_at = index
            break
        for i, label in enumerate(labels):
            key = _HEADER_FIELDS.get(label)
            # Wartość tylko z komórki obok: dalej w wierszu stoi kolumna „Przykład”.
            if key and key not in header and i + 1 < len(row):
                value = _text(row[i + 1])
                if value and _label(value) not in _HEADER_FIELDS:
                    header[key] = value
    if header_at is None:
        return None
    head = table[header_at]
    labels = [_label(c) for c in head]
    col: dict[str, int] = {}
    days: list[tuple[int, date]] = []
    month = None
    for i, (cell, label) in enumerate(zip(head, labels)):
        if label.startswith("miesiąc"):
            col.setdefault("month", i)
        elif label.startswith("numer projektu"):
            col.setdefault("project", i)
        elif label.startswith("numer zadania"):
            col.setdefault("task", i)
        elif label.startswith("rezultat"):
            col.setdefault("description", i)
        elif label.startswith("liczba godzin"):
            col.setdefault("hours", i)
            month = month or _month_from_text(label)
        elif label.startswith("razem"):
            col.setdefault("hours", i)
            month = month or _month_from_text(label)
        elif isinstance(cell, (datetime, date)) and "hours" in col:
            day = cell.date() if isinstance(cell, datetime) else cell
            days.append((i, day))
    if "hours" not in col:
        return None
    if days:
        # Nowszy szablon: pierwsza data w nagłówku to 1. dzień miesiąca (N15).
        first = days[0][1]
        month = f"{first.year}-{first.month:02d}"
    entries: list[PkoEntry] = []
    month_values: list[str] = []
    declared = None
    for row in table[header_at + 1 : header_at + 1 + MAX_ROWS]:
        if any(_label(c).startswith("całkowity czas") for c in row):
            declared = duration_hours(
                row[col["hours"]] if col["hours"] < len(row) else None
            )
            break

        def cell(key: str) -> Any:
            index = col.get(key)
            return row[index] if index is not None and index < len(row) else None

        per_day = tuple(
            (day, value)
            for index, day in days
            if index < len(row)
            and (value := duration_hours(row[index])) is not None
            and value > 0
        )
        hours = duration_hours(cell("hours"))
        if (hours is None or hours == 0) and per_day:
            hours = sum((v for _d, v in per_day), Decimal("0"))
        if hours is None or hours <= 0:
            continue
        entries.append(
            PkoEntry(
                project=_text(cell("project")),
                task=_text(cell("task")),
                description=_text(cell("description")) or "",
                hours=hours,
                days=per_day,
            )
        )
        found = _month_of(cell("month"))
        if found:
            month_values.append(found)
    month_col = col.get("month")
    return ParsedPko(
        consultant=header.get("consultant"),
        pz=header.get("pz"),
        coordinator=header.get("coordinator"),
        month=month,
        month_column=tuple(dict.fromkeys(month_values)),
        month_column_hidden=month_col is not None
        and _column_letter(month_col) in hidden,
        entries=tuple(entries),
        declared_total=declared,
        header_row=header_at + 1,
        columns_hidden=tuple(sorted(hidden)),
    )


def _sheet(content: bytes) -> Optional[tuple[list[list[Any]], list[str]]]:
    import openpyxl

    try:
        with warnings.catch_warnings():
            # „Data Validation extension is not supported” — lista podpowiedzi szablonu.
            warnings.simplefilter("ignore")
            workbook = openpyxl.load_workbook(
                io.BytesIO(content), data_only=True, keep_vba=False
            )
    except Exception as exc:  # noqa: BLE001
        logger.info("timesheet_pko: plik nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        for ws in workbook.worksheets:
            if ws.sheet_state != "visible":
                continue
            rows = [
                list(r)
                for r in ws.iter_rows(
                    max_row=min(ws.max_row, MAX_ROWS + 40),
                    max_col=min(ws.max_column, MAX_COLS),
                    values_only=True,
                )
            ]
            hidden = [k for k, d in ws.column_dimensions.items() if d.hidden]
            # Zakres ukrytych kolumn bywa zapisany jednym wpisem (D–H).
            for key, dim in list(ws.column_dimensions.items()):
                if dim.hidden and dim.min and dim.max and dim.max > dim.min:
                    hidden += [
                        _column_letter(i - 1) for i in range(dim.min, dim.max + 1)
                    ]
            if any(
                "lp." in [_label(c) for c in row]
                and any(_label(c).startswith("numer projektu") for c in row)
                for row in rows[:40]
            ):
                return rows, hidden
        return None
    finally:
        workbook.close()


def parse(content: bytes, mime: str) -> Optional[ParsedPko]:
    if mime not in MIMES:
        return None
    found = _sheet(content)
    return parse_rows(*found) if found is not None else None


def md_from_hours(hours: Decimal, per_md: Decimal) -> Decimal:
    return (hours / per_md).quantize(MD_Q, rounding=ROUND_HALF_UP)


def _hidden_month_text(parsed: ParsedPko, month: str) -> Optional[str]:
    """Opis rozbieżności kolumny miesiąca z nagłówkiem albo ``None``."""

    _year, mon = month.split("-")
    other = [
        value
        for value in parsed.month_column
        if value[-2:] != mon or (not value.startswith("????") and value != month)
    ]
    if not other:
        return None
    names = ", ".join(
        MONTHS_NOMINATIVE[int(v[-2:]) - 1] if v.startswith("????") else month_label(v)
        for v in other
    )
    where = "ukrytej kolumnie" if parsed.month_column_hidden else "kolumnie"
    return f"W {where} „Miesiąc realizacji usług” jest: {names}"


def evaluate(
    parsed: ParsedPko,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
) -> ProofResult:
    """Kontrole Time Sheet z katalogu reguł; MD = godziny / ``fields.md_hours``."""

    result = ProofResult(md_regular=None, md_extra=None)
    sheet = _Group(result, rules, GROUP_TITLE)
    hours = parsed.total_hours
    per_md = _param_dec(rules, "fields.md_hours", "hours", "8")
    per_md = per_md if per_md > 0 else Decimal("8")

    if not parsed.entries:
        sheet.info(
            "Time Sheet bez godzin",
            "Nie ma wierszy z godzinami. MD wpisują Finanse; plik zostaje w NEXUS-ie.",
        )
        result.warn = True
        sheet.close()
        return result

    result.md_regular = md_from_hours(hours, per_md)
    result.md_extra = Decimal("0")

    if parsed.month == month:
        sheet.ok(f"Miesiąc z nagłówka: {month_label(month)}")
    else:
        sheet.fail(
            "proof.month",
            "Time Sheet za inny miesiąc",
            f"W nagłówku: {month_label(parsed.month) if parsed.month else 'brak miesiąca'}.",
        )
    mismatch = _hidden_month_text(parsed, month)
    if mismatch:
        # Tylko ostrzeżenie: miesiąc bierzemy z widocznego nagłówka (12.11.2026).
        sheet.warn(mismatch, "Miesiąc liczymy z widocznego nagłówka tabeli.")

    consultant = name_tokens(parsed.consultant)
    person = name_tokens(person_name)
    if consultant and person and (consultant <= person or person <= consultant):
        sheet.ok("Imię i nazwisko jak w kontrakcie")
    elif consultant:
        sheet.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    else:
        sheet.fail("proof.name_match", "Time Sheet bez imienia i nazwiska kontraktora")

    if parsed.coordinator:
        sheet.info(
            f"Koordynator w Time Sheet: {parsed.coordinator}",
            "Akceptować może też ktoś inny (urlopy, zmiany po stronie klienta).",
        )
    sheet.close()

    sums = _Group(result, rules, "Pola i sumy")
    if sums.on("fields.md_hours"):
        detail = f"{_fmt(hours)} h / {_fmt(per_md)} = {_fmt(result.md_regular)} MD."
        if parsed.declared_total is not None and (
            abs(parsed.declared_total - hours) > TOLERANCE
        ):
            sums.fail(
                "fields.md_hours",
                "Suma „Całkowity czas” inna niż suma wierszy",
                f"W pliku {_fmt(parsed.declared_total)} h, z wierszy {_fmt(hours)} h. {detail}",
            )
        else:
            sums.ok("Godziny policzone od nowa", detail)
    days = parsed.day_totals()
    if sums.on("fields.day_limit") and days:
        limit = _param_dec(rules, "fields.day_limit", "hours", "24")
        worst = max(days, key=lambda d: days[d])
        if days[worst] <= limit:
            sums.ok(
                f"Najwięcej w jednym dniu: {_fmt(days[worst])} h",
                f"Limit {_fmt(limit)} h.",
            )
        else:
            sums.fail(
                "fields.day_limit",
                f"{_fmt(days[worst])} h w dniu {worst.strftime('%d.%m')}",
                f"Limit {_fmt(limit)} h.",
            )
    month_limit(sums, result.md_regular, working_days, other_md)
    sums.close()
    return result


def month_limit(
    group: _Group, md: Decimal, working_days: int, other_md: Decimal
) -> None:
    """``fields.md_month_limit``: MD osoby nie ponad dni robocze, także łącznie
    z rozliczeniami tej osoby u innych klientów w tym miesiącu (Velo, 12.11)."""

    if not group.on("fields.md_month_limit") or working_days <= 0:
        return
    total = md + other_md
    together = f" (razem z innymi klientami: {_fmt(total)} MD)" if other_md > 0 else ""
    if total <= working_days:
        group.ok(f"{_fmt(md)} MD przy {working_days} dniach roboczych{together}")
    else:
        group.fail(
            "fields.md_month_limit",
            f"{_fmt(total)} MD przy {working_days} dniach roboczych",
            "Więcej MD niż dni roboczych"
            + (
                f": u tego klienta {_fmt(md)} MD, u innych {_fmt(other_md)} MD."
                if other_md > 0
                else ": sprawdź, czy godziny nie są za dwóch klientów."
            ),
        )
