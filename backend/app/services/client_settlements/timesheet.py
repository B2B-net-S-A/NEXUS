"""Odczyt Time Sheet konsultanta w godzinach (roadmapa E6.2) i kontrole. Bez bazy.

Szablon „Time Sheet” (XLSX): nagłówek „Project Name”, „Consultant(s)”,
„Date from”, „Date to”, potem tabela „Date · Project · Description · Total
Hours · Billable · Non-billable · Nr strumienia” zakończona wierszem „Total
Hours”. Konsultant bywa kopiuje tabelę na kilka tygodni albo arkuszy, więc
czytamy każdą tabelę z każdego widocznego arkusza.

Godziny do rozliczenia to „Billable”; bez tej kolumny albo przy pustej komórce
„Total Hours” minus „Non-billable”, a tekst w „Billable” (VeloBank: „x” w weekendy
i dni wolne) to 0 h. MD = godziny / ``fields.md_hours`` (domyślnie 8 h). Jedna osoba
może mieć kilka projektów: projekt bierzemy z wiersza, a bez niego z nagłówka.
„Nr strumienia” (albo „Task ID”) trafia do potwierdzenia usług klienta jako
Task ID (odpowiedź rozliczeń z 12.11.2026: „cokolwiek z TS-a konsultanta”).

Ten sam szablon bywa w PDF (tekst z ``pdfplumber``, ``text_rows``): wiersz
„2026-09-01 …” albo „Tuesday 2026.09.01 …” kończy się kolumnami godzin
(„-” to pusta komórka), a koniec to „Total Hours (This month) 78”. Bosch pisze
daty „01-09-2026”, a opis zawinięty w komórce rozbija mu wiersz: data stoi sama,
godziny są w następnej linii (bierzemy je tylko w pełnym komplecie kolumn). Ten sam
odczyt bierze PDF „<osoba> Okres od: · Projekt: … Okres do: · Data Dzień Opis
Godziny Rozliczalne” zakończony „W sumie”. Polski wariant XLSX: tytuł „Time
Sheet”, „Imię Nazwisko”, tabela „Data · Opis zadań · Liczba godzin · Uwagi”
i „Łączna liczba godzin”.

Plik spoza szablonu daje ``None``: wtedy MD wpisują Finanse, a plik zostaje.
Time Sheet za inny miesiąc to kontrola ``proof.month`` bez MD; wyjątki to rok
z zeszłorocznego szablonu (``template_year_fixed``) i daty wierszy z innego
miesiąca przy nagłówku na cały rozliczany miesiąc (``template_month_fixed``).
Odczyt nigdy nie blokuje przyjęcia pliku.
"""

from __future__ import annotations

import calendar
import io
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, replace
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Iterable, Mapping, Optional

from app.services.client_settlements import timesheet_pko
from app.services.client_settlements.declared import (
    month_mismatch,
    pdf_text,
    short_lines,
)
from app.services.client_settlements.rcp_bnp import _dec
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    client_acceptance_mail,
    name_tokens,
)
from app.services.person_workdays import business_days

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
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
    "imię nazwisko": "consultant",
    "imię i nazwisko": "consultant",
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
# Polski wariant szablonu, tylko w arkuszu z tytułem „Time Sheet”: ta sama
# tabela „Data · Liczba godzin” jest w raporcie BIK.
_POLISH_COLUMNS = {
    "data": "date",
    "opis zadań": "description",
    "liczba godzin": "total",
}
_TOTAL_LABELS = ("total hours", "łączna liczba godzin", "w sumie")


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


def _header_columns(row: list[Any], *, polish: bool) -> Optional[dict[str, int]]:
    labels = [_label(c) for c in row]
    if "date" in labels and any(
        label and label.startswith("total hours") for label in labels
    ):
        names = _COLUMNS
    elif polish and "data" in labels and "liczba godzin" in labels:
        names = _POLISH_COLUMNS
    else:
        return None
    columns: dict[str, int] = {}
    for i, label in enumerate(labels):
        if label is None:
            continue
        key = names.get(label)
        if key is None and label.startswith("total hours"):
            key = "total"
        if key is not None and key not in columns:
            columns[key] = i
    return columns


def _cell(row: list[Any], columns: Mapping[str, int], key: str) -> Any:
    index = columns.get(key)
    return row[index] if index is not None and index < len(row) else None


def _marker(cell: Any) -> bool:
    """Niepusty tekst, który nie jest liczbą (znacznik „x” dnia bez pracy)."""

    return isinstance(cell, str) and bool(cell.strip()) and _dec(cell) is None


def is_sum_row(
    day: Optional[date],
    label: Optional[str],
    hours: Decimal,
    table: Iterable[Any],
) -> bool:
    """Wiersz bez daty i opisu z godzinami równymi sumie co najmniej dwóch
    wcześniejszych wpisów tabeli to suma pod tabelą, nie praca."""

    rows = list(table)
    if day is not None or label or len(rows) < 2:
        return False
    return abs(sum((e.hours for e in rows), Decimal("0")) - hours) <= TOLERANCE


def parse_rows(sheets: Iterable[list[list[Any]]]) -> Optional[ParsedTimesheet]:
    """Wiersze arkuszy → Time Sheet. Wydzielone, żeby testy nie wymagały XLSX."""

    header: dict[str, Any] = {}
    entries: list[TsEntry] = []
    declared: Optional[Decimal] = None
    found_table = False
    for rows in sheets:
        columns: Optional[dict[str, int]] = None
        table: list[TsEntry] = []
        titled = False
        for row in rows:
            titled = titled or any(_label(c) == "time sheet" for c in row)
            for i, cell in enumerate(row):
                key = _HEADER_LABELS.get(_label(cell) or "")
                if key and key not in header:
                    value = _after(row, i)
                    if value is not None:
                        header[key] = value
            new_columns = _header_columns(row, polish=titled)
            if new_columns is not None:
                columns, found_table, table = new_columns, True, []
                continue
            if columns is None:
                continue
            labels = [_label(c) or "" for c in row]
            total_at = next(
                (
                    i
                    for i, label in enumerate(labels)
                    if label.startswith(_TOTAL_LABELS)
                ),
                None,
            )
            if total_at is not None:
                value = _dec(_after(row, total_at))
                if value is not None:
                    declared = (declared or Decimal("0")) + value
                columns = None
                continue
            raw_billable = _cell(row, columns, "billable")
            if _marker(raw_billable):
                # Tekst w „Billable” to dzień bez godzin, nie powód, by liczyć
                # „Total Hours”: VeloBank ma 8 w Total w każdym dniu kalendarza,
                # a weekendy i dni wolne oznacza „x” (próba IX–X 2026: 30 MD z
                # wierszy zamiast 20 z sumy pliku i arkusza podpisanego przez klienta).
                continue
            description = _text(_cell(row, columns, "description"))
            billable = _dec(raw_billable)
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
            entry = TsEntry(
                day=_day(_cell(row, columns, "date")),
                project=_text(_cell(row, columns, "project")),
                description=description or "",
                hours=hours,
                task_id=_text(_cell(row, columns, "task_id")),
            )
            if is_sum_row(entry.day, entry.project or entry.description, hours, table):
                # Suma pod tabelą bez etykiety „Total Hours” (próba 22.11.2026:
                # szła jako wpis projektu z nagłówka i podwajała MD).
                declared = (declared or Decimal("0")) + hours
                columns = None
                continue
            table.append(entry)
            entries.append(entry)
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


# „2026-09-01”, „Tuesday 2026.09.01”, a w Time Sheet Boscha „01-09-2026”.
_TEXT_DAY = re.compile(
    r"^(?:[A-Za-ząćęłńóśźż]+\s+)?"
    r"(?:(\d{4})[-.](\d{1,2})[-.](\d{1,2})|(\d{1,2})[-.](\d{1,2})[-.](\d{4}))"
    r"(?:\s+(.*))?$"
)
_TEXT_NUMBER = re.compile(r"^\d+(?:[.,]\d+)?$")
_TEXT_FIELDS = (
    ("project name", "Project Name"),
    ("consultant(s)", "Consultant(s)"),
    ("date from", "Date from"),
    ("date to", "Date to"),
)
_OKRES_OD = re.compile(r"^(.*?)\s*okres\s+od\s*:\s*(\S+)", re.IGNORECASE)
_OKRES_DO = re.compile(r"^projekt\s*:\s*(.*?)\s*okres\s+do\s*:\s*(\S+)", re.IGNORECASE)
_TEXT_HEADER = ["Date", "Description", "Total Hours", "Billable", "Non-billable"]


def _text_hours(
    tokens: list[str], width: int, *, least: int
) -> tuple[int, Optional[list[Any]]]:
    """Ostatnie kolumny wiersza (liczby albo „-”), od ``least`` do ``width``:
    (ile ich jest, wartości Total · Billable · Non-billable)."""

    count = 0
    while count < min(width, len(tokens)):
        token = tokens[-1 - count]
        if token != "-" and not _TEXT_NUMBER.match(token):
            break
        count += 1
    if count < least:
        return 0, None
    tail = tokens[len(tokens) - count :]
    values: list[Any] = [None if t == "-" else _dec(t) for t in tail]
    return count, values + [None] * (3 - count)


def _text_date(found: re.Match[str]) -> Optional[date]:
    """Data z ``_TEXT_DAY``: rok-miesiąc-dzień albo dzień-miesiąc-rok."""

    year, month, day = found.group(1, 2, 3)
    if year is None:
        day, month, year = found.group(4, 5, 6)
    try:
        return date(int(year), int(month), int(day))
    except ValueError:
        return None


def text_rows(text: str) -> Optional[list[list[Any]]]:
    """Tekst PDF Time Sheet → wiersze jak z arkusza (dla ``parse_rows``)."""

    lines = [" ".join(line.split()) for line in short_lines(text).splitlines()]
    fields: list[list[Any]] = []
    rows: list[list[Any]] = []
    width = 0
    least = 0
    # Data wiersza bez godzin: dzień wolny albo opis zawinięty w komórce.
    waiting: Optional[tuple[date, list[str]]] = None
    titled = any(line.lower().startswith("time sheet") for line in lines)
    for line in lines:
        low = line.lower()
        if not width:
            for label, name in _TEXT_FIELDS:
                if titled and low.startswith(label):
                    value = line[len(label) :].strip(" :")
                    if value:
                        fields.append([name, value])
            if found := _OKRES_OD.match(line):
                fields += [
                    ["Consultant(s)", found.group(1)],
                    ["Date from", found.group(2)],
                ]
            if found := _OKRES_DO.match(line):
                fields += [
                    ["Project Name", found.group(1)],
                    ["Date to", found.group(2)],
                ]
        polish = low.startswith("data dzień opis godziny")
        is_header = (titled and "total hours" in low and "billable" in low) or polish
        if is_header:
            width = 3 if "non-billable" in low else 2
            # Wzór „Okres od”: pusta kolumna „Rozliczalne” znika z tekstu PDF.
            least = 1 if polish else width
            rows.append(list(_TEXT_HEADER))
            waiting = None
            continue
        if not width:
            continue
        tokens = line.split()
        if low.startswith(_TOTAL_LABELS):
            numbers = [t for t in tokens if _TEXT_NUMBER.match(t)]
            if numbers:
                rows.append(["Total Hours", _dec(numbers[0])])
            waiting = None
            continue
        found = _TEXT_DAY.match(line)
        if not found:
            if waiting is not None:
                # Opis zawinięty w komórce (Time Sheet Boscha, próba IX–X 2026): data
                # stoi sama, a godziny są w następnej linii. Tylko pełny komplet
                # kolumn godzin, żeby liczba z opisu („wydanie 2026”) nie była godziną.
                count, hours = _text_hours(tokens, width, least=width)
                if hours is not None:
                    day, rest = waiting
                    description = " ".join(rest + tokens[: len(tokens) - count])
                    rows.append([day, description, *hours])
                waiting = None
            continue
        waiting = None
        day = _text_date(found)
        if day is None:
            continue
        rest = (found.group(7) or "").split()
        count, hours = _text_hours(rest, width, least=least)
        if hours is None:
            waiting = (day, rest)
            continue
        rows.append([day, " ".join(rest[: len(rest) - count]), *hours])
    if not rows:
        return None
    return fields + rows


def _pdf(content: bytes) -> Optional[ParsedTimesheet]:
    text = pdf_text(content)
    rows = text_rows(text) if text else None
    return parse_rows([rows]) if rows else None


def parse(content: bytes, mime: str) -> Optional[ParsedTimesheet]:
    if mime == PDF:
        return _pdf(content)
    if mime != XLSX:
        return None
    sheets = _sheets(content)
    return parse_rows(sheets) if sheets is not None else None


def month_business_days(month: str) -> list[date]:
    """Dni robocze miesiąca ``RRRR-MM`` (bez weekendów i polskich świąt)."""

    year, number = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, number)[1]
    return business_days(date(year, number, 1), date(year, number, last))


def template_year_fixed(
    parsed: ParsedTimesheet, month: str
) -> Optional[ParsedTimesheet]:
    """Time Sheet z rokiem z zeszłorocznego szablonu (ERSTE 23.11.2026: „TS -
    Październik” z datami 2025, godziny w dni robocze 2026) przeniesiony na
    rozliczany rok. Tylko gdy ten sam miesiąc, wszystkie wpisy w nim, każdy dzień
    z godzinami jest dniem roboczym rozliczanego miesiąca, a choć jeden nie jest
    dniem roboczym w roku z pliku. Pasujący do obu kalendarzy plik zostaje
    plikiem za inny miesiąc. ``None`` = bez zmiany."""

    if parsed.month is None or parsed.month == month or parsed.date_from is not None:
        return None
    year, number = int(month[:4]), int(month[5:7])
    file_year = int(parsed.month[:4])
    if int(parsed.month[5:7]) != number:
        return None
    days = {e.day for e in parsed.entries}
    if None in days or any(d.year != file_year or d.month != number for d in days):
        return None
    worked = {d.day for d in days}
    target = {d.day for d in month_business_days(month)}
    in_file = {d.day for d in month_business_days(parsed.month)}
    if not worked <= target or worked <= in_file:
        return None
    entries = tuple(
        replace(e, day=e.day.replace(year=year)) for e in parsed.entries if e.day
    )
    return replace(parsed, entries=entries)


def template_month_fixed(
    parsed: ParsedTimesheet, month: str
) -> Optional[ParsedTimesheet]:
    """Time Sheet z nagłówkiem „Date from/Date to” na cały rozliczany miesiąc,
    a z datami wierszy z jednego innego miesiąca: szablon skopiowany bez zmiany
    dat (Bosch, próba IX–X 2026: nagłówek wrzesień, 30 wierszy z czerwca, godziny
    równe fakturze). Decyzja Artura z 24.11.2026: liczymy za miesiąc z nagłówka,
    z informacją. Wiersze z dwóch miesięcy, bez dat albo z dniem spoza
    rozliczanego miesiąca zostają wpisami spoza miesiąca. ``None`` = bez zmiany."""

    year, number = int(month[:4]), int(month[5:7])
    last = calendar.monthrange(year, number)[1]
    if parsed.date_from != date(year, number, 1) or parsed.date_to != date(
        year, number, last
    ):
        return None
    days = {e.day for e in parsed.entries}
    if not days or None in days:
        return None
    months = {(d.year, d.month) for d in days if d is not None}
    if len(months) != 1 or months == {(year, number)}:
        return None
    if max(d.day for d in days if d is not None) > last:
        return None
    entries = tuple(
        replace(e, day=e.day.replace(year=year, month=number))
        for e in parsed.entries
        if e.day
    )
    return replace(parsed, entries=entries)


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
    other_md: Decimal = Decimal("0"),
    client_mail: Optional[bool] = None,
    acceptor: str = "klienta",
    signed_sheet: bool = False,
) -> ProofResult:
    """Kontrole Time Sheet z katalogu reguł; MD z godzin, bez pracy dodatkowej.

    ``client_mail``: czy w mailach miesiąca jest wiadomość klienta
    (``acceptance_mail.from_client``); ``None`` = nadawcy nie odczytano.
    ``acceptor``: kto akceptuje (``mail_text.Senders.who``, w FIX „PM-a firmy”).
    ``signed_sheet``: klient podpisał arkusz zbiorczy z MD tej osoby (``signoffs``).
    ``proof.excel_with_mail`` żąda maila tylko wtedy, gdy podpisu brak; zgodność
    MD z arkuszem sprawdza ``service._signed_checks``."""

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

    fixed = template_year_fixed(parsed, month)
    if fixed is not None:
        sheet.info(
            f"Rok w szablonie: {(parsed.month or '')[:4]}",
            f"Dni z godzinami to dni robocze {month}, a nie {parsed.month}: "
            "liczymy jako rozliczany miesiąc.",
        )
        parsed = fixed
    moved = template_month_fixed(parsed, month)
    if moved is not None:
        source = next(e.day for e in parsed.entries if e.day)
        sheet.info(
            f"Daty wierszy z innego miesiąca: {source.year}-{source.month:02d}",
            f"Nagłówek obejmuje cały {month}, a wiersze mają daty z "
            f"{source.year}-{source.month:02d} (szablon z innego miesiąca): "
            "liczymy jako rozliczany miesiąc.",
        )
        parsed = moved

    # Plik za inny miesiąc (np. szablon z rokiem 2025): kontrola bez MD.
    other_month = parsed.month is not None and parsed.month != month
    if parsed.month == month:
        sheet.ok(f"Miesiąc z Time Sheet: {month}")
    elif other_month:
        month_mismatch(sheet, "Time Sheet za inny miesiąc", f"W pliku: {parsed.month}.")
    else:
        sheet.fail("proof.month", "Time Sheet za inny miesiąc", "W pliku: brak dat.")
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
        if signed_sheet:
            # Próba IX–X 2026: akceptacją klienta jest podpis na arkuszu zbiorczym,
            # mailem akceptuje tylko część kierowników.
            sheet.ok("Godziny zaakceptowane podpisem klienta na arkuszu zbiorczym")
        elif not has_mail:
            sheet.fail(
                "proof.excel_with_mail",
                "Brak maila z akceptacją godzin",
                "Dołącz mail z akceptacją (MSG, EML albo PDF z wydrukiem).",
            )
        else:
            client_acceptance_mail(
                sheet, "proof.excel_with_mail", client_mail, who=acceptor
            )
            if client_mail:
                sheet.ok("Mail z akceptacją godzin jest")

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
    timesheet_pko.month_limit(sums, result.md_regular, working_days, other_md)
    sums.close()
    if other_month:
        result.md_regular = None
        result.md_extra = None
    return result
