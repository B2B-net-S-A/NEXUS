"""Eksport tygodniowych Time Sheetów z SAP Fieldglass (EY) i jego kontrole. Bez bazy.

Konsultant przysyła co miesiąc „timeSheet.worker.list….xlsx”: wiersz nagłówka
„Status, ID, Revision, …, Start Date, End, ST, OT, DT, Others, NB” i wiersz na
tydzień (sobota–piątek) z godzinami ST. Eksport bywa jedną kolumną z tekstem
CSV w każdej komórce, więc taki wiersz dzielimy po przecinkach.

Godziny miesiąca: tydzień w całości w miesiącu liczymy w całości. Tydzień na
przełomie (26.09–02.10) nie ma podziału na dni, więc dzielimy go tylko, gdy
jest pełny: ST = ``fields.md_hours`` × dni robocze tygodnia; wtedy do miesiąca
idzie ``fields.md_hours`` × jego dni robocze w tym miesiącu. Niepełny tydzień
na przełomie, tydzień odrzucony albo w szkicu = bez MD (dzieli człowiek).
Kilka rewizji jednego ID: liczy się najwyższa.

Eksport nie ma imienia i nazwiska konsultanta (tylko przełożonego), więc
``proof.name_match`` zgłasza jego brak według poziomu reguły. „Pending Approval”
to informacja: Finanse fakturują także tygodnie czekające na akceptację.
Plik spoza wzoru daje ``None``.
"""

from __future__ import annotations

import csv
import io
import logging
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Mapping, Optional

from app.services.client_settlements import timesheet_pko
from app.services.client_settlements.rcp_bnp import _dec
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)
from app.services.client_settlements.timesheet import month_business_days
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
SOURCE = "Time Sheet Fieldglass"
MD_Q = Decimal("0.001")
MAX_ROWS = 200
MAX_COLS = 30
#: Statusy, z których bierzemy godziny; inne (np. „Rejected”, „Draft”) = bez MD.
COUNTED = ("approved", "pending approval", "submitted")
_REQUIRED = ("status", "id", "start date", "end", "st")


@dataclass(frozen=True)
class FgWeek:
    ts_id: str
    revision: int
    status: str
    start: date
    end: date
    regular: Decimal
    #: OT + DT + Others: nadgodziny i inne stawki poza ST.
    extra: Decimal


@dataclass(frozen=True)
class ParsedFieldglass:
    weeks: tuple[FgWeek, ...]
    consultant: Optional[str]


def _cells(row: tuple[Any, ...]) -> list[str]:
    values = [c for c in row if c is not None and str(c).strip() != ""]
    if len(values) == 1 and isinstance(values[0], str) and "," in values[0]:
        try:
            return [v.strip() for v in next(csv.reader([values[0]]))]
        except csv.Error:
            # Komórka z tekstem wielowierszowym to nie wiersz CSV z Fieldglass.
            return [values[0].strip()]
    return ["" if c is None else str(c).strip() for c in row]


def _day(text: str) -> Optional[date]:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_rows(rows: list[list[str]]) -> Optional[ParsedFieldglass]:
    """Wiersze arkusza (już podzielone na komórki) → tygodnie. Wydzielone dla testów."""

    columns: Optional[dict[str, int]] = None
    latest: dict[str, FgWeek] = {}
    consultant: Optional[str] = None
    for row in rows:
        labels = [c.lower() for c in row]
        if columns is None:
            if all(label in labels for label in _REQUIRED):
                columns = {label: i for i, label in enumerate(labels) if label}
            continue

        def cell(key: str) -> str:
            index = columns.get(key)
            return row[index] if index is not None and index < len(row) else ""

        start, end = _day(cell("start date")), _day(cell("end"))
        regular = _dec(cell("st"))
        if not cell("id") or start is None or end is None or regular is None:
            continue
        extra = sum(
            (_dec(cell(key)) or Decimal("0") for key in ("ot", "dt", "others")),
            Decimal("0"),
        )
        week = FgWeek(
            ts_id=cell("id"),
            revision=int(_dec(cell("revision")) or 0),
            status=cell("status"),
            start=start,
            end=end,
            regular=regular,
            extra=extra,
        )
        known = latest.get(week.ts_id)
        if known is None or week.revision > known.revision:
            latest[week.ts_id] = week
        consultant = consultant or (cell("worker") or None)
    if columns is None or not latest:
        return None
    weeks = sorted(latest.values(), key=lambda w: w.start)
    return ParsedFieldglass(weeks=tuple(weeks), consultant=consultant)


def parse(content: bytes, mime: str) -> Optional[ParsedFieldglass]:
    if mime != XLSX:
        return None
    import openpyxl

    try:
        workbook = openpyxl.load_workbook(
            io.BytesIO(content), read_only=True, data_only=True
        )
    except Exception as exc:  # noqa: BLE001 — uszkodzony plik nie blokuje przyjęcia
        logger.info("rozliczenia: XLSX nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        for sheet in workbook.worksheets:
            if getattr(sheet, "sheet_state", "visible") != "visible":
                continue
            rows = [
                _cells(row)
                for row in sheet.iter_rows(
                    max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
                )
            ]
            parsed = parse_rows(rows)
            if parsed is not None:
                return parsed
        return None
    finally:
        workbook.close()


def _period(week: FgWeek) -> str:
    return f"{week.start.strftime('%d.%m')}–{week.end.strftime('%d.%m')}"


def evaluate(
    parsed: ParsedFieldglass,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
) -> ProofResult:
    result = ProofResult(md_regular=None, md_extra=None)
    group = _Group(result, rules, SOURCE)
    month_days = set(month_business_days(month))
    per_md = _param_dec(rules, "fields.md_hours", "hours", "8")
    per_md = per_md if per_md > 0 else Decimal("8")

    hours = Decimal("0")
    extra = Decimal("0")
    covered: set[date] = set()
    weeks_in_month: list[FgWeek] = []
    unsplit: list[str] = []
    for week in parsed.weeks:
        days = business_days(week.start, week.end)
        inside = [d for d in days if d in month_days]
        if not inside:
            continue
        weeks_in_month.append(week)
        covered.update(inside)
        if week.status.lower() not in COUNTED:
            unsplit.append(f"Tydzień {_period(week)}: status „{week.status}”")
            continue
        if len(inside) == len(days):
            hours += week.regular
            extra += week.extra
        elif week.regular == per_md * len(days) and week.extra == 0:
            hours += per_md * len(inside)
        else:
            unsplit.append(
                f"Tydzień {_period(week)} na przełomie miesięcy: {_fmt(week.regular)} h"
            )

    if not weeks_in_month:
        group.info(
            f"{SOURCE} bez tygodni z {month}",
            "MD z tego pliku nie wpisujemy.",
        )
        result.warn = True
        group.close()
        return result

    approved = sum(1 for w in weeks_in_month if w.status.lower() == "approved")
    group.info(
        f"Zatwierdzone w Fieldglass: {approved} z {len(weeks_in_month)} tygodni",
        None
        if approved == len(weeks_in_month)
        else "Pozostałe czekają na akceptację przełożonego w Fieldglass.",
    )
    for title in unsplit:
        group.info(
            title,
            "Nie wiadomo, ile godzin przypada na ten miesiąc. MD wpisują Finanse.",
        )
    missing = sorted(month_days - covered)
    if missing:
        group.warn(
            f"Dni robocze bez tygodnia w pliku: {len(missing)}",
            "Brak: " + ", ".join(d.strftime("%d.%m") for d in missing) + ".",
        )
    if extra:
        group.warn(
            f"Nadgodziny w Fieldglass: {_fmt(extra)} h",
            "OT/DT/Others nie wchodzą do MD; dodatkową pracę wpisują Finanse.",
        )
    on_doc, person = name_tokens(parsed.consultant), name_tokens(person_name)
    if on_doc and person and (on_doc <= person or person <= on_doc):
        group.ok("Imię i nazwisko jak w kontrakcie")
    elif on_doc:
        group.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    else:
        group.fail(
            "proof.name_match",
            "Eksport Fieldglass bez imienia i nazwiska",
            "W eksporcie jest tylko przełożony; plik przyszedł do tego kontraktu.",
        )
    group.close()

    if unsplit:
        result.warn = True
        return result
    result.md_regular = (hours / per_md).quantize(MD_Q, rounding=ROUND_HALF_UP)
    result.md_extra = Decimal("0")
    sums = _Group(result, rules, "Pola i sumy")
    if sums.on("fields.md_hours"):
        sums.ok(
            "MD z tygodni Fieldglass",
            f"{_fmt(hours)} h / {_fmt(per_md)} = {_fmt(result.md_regular)} MD.",
        )
    timesheet_pko.month_limit(sums, result.md_regular, working_days, other_md)
    sums.close()
    return result
