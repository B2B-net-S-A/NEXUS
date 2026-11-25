"""Odczyt raportu godzin konsultanta u klienta BIK. Bez bazy.

Układy z archiwum rozliczeń IX–XI 2026:

* szablon BIK od września 2026: tytuł „Rozliczenie czasu pracy” (bywa
  „Roliczenie”), pola „Imię i nazwisko”, „Miesiąc” (data albo nazwa
  miesiąca), „Numer zamówienia”, tabela „Numer jiry · Nazwa zadania · Data ·
  Liczba godzin” zakończona wierszem „Suma godzin”; pod nią „MDs narastająco”;
* starszy szablon: tabela „Nazwa zadania · Data · Liczba godzin”, suma
  w wierszu „Liczba godzin” pod tabelą, niżej „Podsumowanie” i „Zużycie MD”;
* ten sam szablon wyeksportowany do PDF (tabele z ``pdfplumber``); długie
  opisy wychodzą tam poza komórkę i psują część wierszy, więc przy
  rozbieżności MD liczymy z „Sumy godzin” z ostrzeżeniem;
* tabela dni „Data · Dzień · Ilość godzin” bez tytułu i nazwiska (konsultant,
  który nie przeszedł na szablon), suma pod tabelą bez etykiety;
* PDF bez tabel do odczytu (``text_rows``): „Za miesiąc wrzesien 2026”,
  „Zadanie Data Czas (godz.)”, wiersze „BIK 1.09.2026 8”, „Suma 24 h”, albo
  „Miesiąc 01.09.2026”, „Nazwa zadania Data Liczba godzin”, dni „1-09”
  i „Razem 160”. Długi opis zawija się w PDF: data bywa sama w linii, a
  godziny na końcu następnej.

Suma w pliku to często wzór bez zapisanej wartości (plik zapisany poza
Excelem): wtedy godziny liczymy z wierszy, bez porównania. Ukryte wiersze też
liczymy, bo liczy je wzór sumy w Excelu (wrzesień 2026: rozliczenia widziały
140 h, a w pliku było więcej). MD = godziny / ``fields.md_hours``.

Pusty szablon (np. wzór odesłany w wątku maila) daje odczyt bez godzin. Plik
spoza tych układów daje ``None``: wtedy MD wpisują Finanse. Raport za inny
miesiąc to kontrola ``proof.month`` bez MD.

Wiersze z datami z szablonu innego miesiąca albo roku przy polu „Miesiąc” równym
rozliczanemu to od 25.11.2026 informacja, nie uwaga, gdy dni z godzinami są dniami
roboczymi rozliczanego miesiąca, a nie miesiąca z dat (``template_dates_month``,
decyzja Artura). Bez takiego dowodu zostaje uwaga „Wiersze z datą spoza miesiąca”.
"""

from __future__ import annotations

import io
import logging
import re
import warnings
from collections import Counter
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from app.services.client_settlements import template_month, xlsx
from app.services.client_settlements.declared import (
    DOCX,
    MAX_LINE,
    docx_text,
    month_mismatch,
)
from app.services.client_settlements.mail_text import month_label
from app.services.client_settlements.rcp_checks import (
    NOTE_ROW_DATES,
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)
from app.services.client_settlements.timesheet import _day, _file_words, is_sum_row
from app.services.client_settlements.timesheet_pko import (
    _month_of,
    duration_hours,
    md_from_hours,
    month_limit,
)

logger = logging.getLogger(__name__)

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
PDF = "application/pdf"
GROUP_TITLE = "Time Sheet"
TOLERANCE = Decimal("0.01")
MAX_ROWS = 400
MAX_COLS = 30

_TITLE = re.compile(r"\bro(?:z)?liczenie\s+czasu\s+pracy\b", re.IGNORECASE)
_HOURS_LABELS = ("liczba godzin", "ilość godzin")
#: „Czas (godz.)” i „Czas- (godz.)”: wariant szablonu z próby VI–VIII 2026.
_TIME_HOURS = re.compile(r"^czas\W*\(?\s*godz")
_TOTAL_LABELS = ("suma godzin", "liczba godzin", "suma", "razem", "łącznie")
# Pod tabelą szablonu: narastające MD i podsumowanie, nie praca w miesiącu.
_END_PREFIXES = ("mds narastająco", "zużycie md", "podsumowanie")
# Pole „Miesiąc” sformatowane w Excelu jako „mmm rr” („sie 26” w PDF).
_SHORT_MONTH = re.compile(r"([a-ząćęłńóśźż]{3})[a-ząćęłńóśźż.]*\s+'?(\d{2}|\d{4})")
_SHORT_MONTHS = (
    "sty",
    "lut",
    "mar",
    "kwi",
    "maj",
    "cze",
    "lip",
    "sie",
    "wrz",
    "paź",
    "lis",
    "gru",
)
# Data wiersza „1-08” (Excel „d-mm”) w PDF: rok z pola „Miesiąc”.
_SHORT_DAY = re.compile(r"(\d{1,2})[-.](\d{1,2})")
_FIELDS = {
    "imię i nazwisko": "consultant",
    "miesiąc": "month",
    "numer zamówienia": "order_number",
}


@dataclass(frozen=True)
class BikEntry:
    day: Optional[date]
    task: Optional[str]
    description: str
    hours: Decimal
    hidden: bool = False


@dataclass(frozen=True)
class ParsedBik:
    source: str
    consultant: Optional[str]
    #: Miesiąc z pola „Miesiąc” (``RRRR-MM``); bez roku rok z dat wierszy.
    month: Optional[str]
    order_number: Optional[str]
    entries: tuple[BikEntry, ...]
    #: „Suma godzin” pod tabelą; ``None``, gdy wzór bez zapisanej wartości.
    declared_total: Optional[Decimal]

    @property
    def rows_hours(self) -> Decimal:
        return sum((e.hours for e in self.entries), Decimal("0"))

    @property
    def rows_match_total(self) -> bool:
        return (
            self.declared_total is None
            or abs(self.declared_total - self.rows_hours) <= TOLERANCE
        )

    @property
    def total_hours(self) -> Decimal:
        """Godziny do MD: z wierszy; w PDF przy rozbieżności z „Sumy godzin”."""

        if self.source == "pdf" and not self.rows_match_total:
            return self.declared_total or Decimal("0")
        return self.rows_hours

    @property
    def hidden_hours(self) -> Decimal:
        return sum((e.hours for e in self.entries if e.hidden), Decimal("0"))

    def entries_month(self) -> Optional[str]:
        counts = Counter(
            f"{e.day.year}-{e.day.month:02d}" for e in self.entries if e.day
        )
        return counts.most_common(1)[0][0] if counts else None

    def day_totals(self) -> dict[date, Decimal]:
        out: dict[date, Decimal] = {}
        for entry in self.entries:
            if entry.day is not None:
                out[entry.day] = out.get(entry.day, Decimal("0")) + entry.hours
        return out


def _label(cell: Any) -> str:
    if not isinstance(cell, str):
        return ""
    return " ".join(cell.split()).strip().rstrip(":").lower()


def _text(cell: Any) -> Optional[str]:
    if cell is None:
        return None
    if isinstance(cell, float) and cell.is_integer():
        cell = int(cell)
    text = " ".join(str(cell).split())
    return text or None


def _after(row: list[Any], index: int) -> Any:
    return next((v for v in row[index + 1 :] if v not in (None, "")), None)


def _hours_label(label: str) -> bool:
    return label in _HOURS_LABELS or bool(_TIME_HOURS.match(label))


def _header(row: list[Any]) -> Optional[dict[str, int]]:
    """Wiersz nagłówka tabeli: „Data” i „Liczba godzin” (albo „Ilość godzin”,
    „Czas (godz.)”)."""

    labels = [_label(c) for c in row]
    if "data" not in labels:
        return None
    hours = next((i for i, lb in enumerate(labels) if _hours_label(lb)), None)
    if hours is None:
        return None
    columns = {"date": labels.index("data"), "hours": hours}
    for i, label in enumerate(labels):
        if label.startswith("numer jir"):
            columns.setdefault("task", i)
        elif label.startswith("nazwa zadania") or label == "zadanie":
            columns.setdefault("description", i)
        elif label == "dzień":
            columns.setdefault("weekday", i)
    return columns


def _month(cell: Any) -> Optional[str]:
    found = _month_of(cell)
    if found or not isinstance(cell, str):
        return found
    match = _SHORT_MONTH.fullmatch(cell.strip().lower())
    if not match or match.group(1) not in _SHORT_MONTHS:
        return None
    year = match.group(2)
    year = f"20{year}" if len(year) == 2 else year
    return f"{year}-{_SHORT_MONTHS.index(match.group(1)) + 1:02d}"


def _row_day(cell: Any, month: Optional[str]) -> Optional[date]:
    found = _day(cell)
    if found or month is None or month.startswith("????"):
        return found
    match = _SHORT_DAY.fullmatch(str(cell or "").strip())
    if not match or int(match.group(2)) != int(month[-2:]):
        return None
    try:
        return date(int(month[:4]), int(match.group(2)), int(match.group(1)))
    except ValueError:
        return None


def _number(cell: Any) -> Optional[Decimal]:
    if isinstance(cell, bool) or hasattr(cell, "year"):
        return None
    return duration_hours(cell)


def parse_rows(
    rows: Iterable[list[Any]],
    *,
    source: str = "xlsx",
    hidden_rows: Iterable[int] = (),
    title: bool = False,
) -> Optional[ParsedBik]:
    """Wiersze arkusza albo tabel PDF → raport. Wydzielone dla testów bez plików.

    ``hidden_rows`` to indeksy (od 0) ukrytych wierszy, ``title`` — tytuł
    „Rozliczenie czasu pracy” znaleziony poza wierszami (tekst strony PDF)."""

    table = [list(r) for r in rows][:MAX_ROWS]
    hidden = set(hidden_rows)
    fields: dict[str, Any] = {}
    titled = title
    columns: Optional[dict[str, int]] = None
    header_at = -1
    for index, row in enumerate(table):
        if any(isinstance(c, str) and _TITLE.search(c) for c in row):
            titled = True
        columns = _header(row)
        if columns is not None:
            header_at = index
            break
        for i, cell in enumerate(row):
            key = _FIELDS.get(_label(cell))
            if key and key not in fields:
                fields[key] = _after(row, i)
    if columns is None:
        return None
    # Bez tytułu tylko tabela dni („Data · Dzień · Ilość godzin”): inne arkusze
    # z kolumną „Data” to nie raport BIK.
    if not titled and "weekday" not in columns:
        return None

    month = _month(fields.get("month"))

    def cell(row: list[Any], key: str) -> Any:
        index = columns.get(key)
        return row[index] if index is not None and index < len(row) else None

    entries: list[BikEntry] = []
    declared: Optional[Decimal] = None
    for index in range(header_at + 1, len(table)):
        row = table[index]
        if _header(row) is not None:
            # Nagłówek tabeli powtórzony na kolejnej stronie PDF.
            continue
        labels = [_label(c) for c in row]
        total_at = next((i for i, lb in enumerate(labels) if lb in _TOTAL_LABELS), None)
        day = _row_day(cell(row, "date"), month)
        if total_at is not None and day is None:
            declared = _number(_after(row, total_at))
            break
        if any(lb.startswith(_END_PREFIXES) for lb in labels):
            break
        if day is None and "weekday" in columns and not any(labels):
            numbers = [n for c in row if (n := _number(c)) is not None]
            if len(numbers) == 1:
                # Tabela dni: suma pod tabelą bez etykiety.
                declared = numbers[0]
                break
        hours = _number(cell(row, "hours"))
        if hours is None or hours <= 0:
            continue
        task = _text(cell(row, "task"))
        description = _text(cell(row, "description"))
        if is_sum_row(day, task or description, hours, entries):
            # Suma pod tabelą bez etykiety (próba 22.11.2026: liczona jako
            # wpis, MD podwójne).
            declared = hours
            break
        entries.append(
            BikEntry(
                day=day,
                task=task,
                description=description or "",
                hours=hours,
                hidden=index in hidden,
            )
        )
    parsed = ParsedBik(
        source=source,
        consultant=_text(fields.get("consultant")),
        month=None,
        order_number=_text(fields.get("order_number")),
        entries=tuple(entries),
        declared_total=declared,
    )
    if month and month.startswith("????"):
        # „Październik” bez roku: rok z dat wierszy.
        found = parsed.entries_month()
        month = f"{found[:4]}-{month[-2:]}" if found else None
    return replace(parsed, month=month)


_TEXT_DAY = re.compile(
    r"(?<![\w-])(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[-.]\d{1,2}(?:[-.]\d{4})?)(?![\w-])"
)
_TEXT_HOURS = re.compile(r"^\d+(?:[.,]\d+)?$")
_TEXT_TAIL = re.compile(r"\s(\d+(?:[.,]\d+)?)$")
_TEXT_TOTAL = re.compile(
    r"^(?:suma\s+godzin|suma|razem|łącznie)\s*:?\s*(\d+(?:[.,]\d+)?)\s*h?$",
    re.IGNORECASE,
)
_TEXT_NAME = re.compile(r"^imię\s+i\s+nazwisko\s*:?\s*(.+?)[.\s]*$", re.IGNORECASE)
_TEXT_MONTH = re.compile(r"^(?:za\s+)?miesiąc\s*:?\s*(.+)$", re.IGNORECASE)
_TEXT_HEADER = re.compile(r"\bdata\b.*(liczba\s+godzin|czas\s*\(godz)", re.IGNORECASE)


def text_rows(text: str) -> list[list[Any]]:
    """Tekst strony PDF → wiersze jak z arkusza (pola, nagłówek, dni, suma)."""

    rows: list[list[Any]] = []
    header = False
    pending: Optional[tuple[str, str]] = None
    for raw in text.splitlines():
        if len(raw) > MAX_LINE:
            continue
        line = " ".join(raw.split())
        if not header:
            if found := _TEXT_NAME.match(line):
                rows.append(["Imię i nazwisko", found.group(1)])
            elif found := _TEXT_MONTH.match(line):
                value = found.group(1).strip()
                rows.append(["Miesiąc", _day(value) or value])
            elif _TEXT_HEADER.search(line):
                rows.append(["Nazwa zadania", "Data", "Liczba godzin"])
                header = True
            continue
        if found := _TEXT_TOTAL.match(line):
            rows.append(["Suma godzin", found.group(1)])
            break
        # Godziny to ostatni token linii, data stoi przed nimi („7.5” to nie dzień).
        tail = _TEXT_TAIL.search(line)
        head = line[: tail.start()] if tail else line
        days = list(_TEXT_DAY.finditer(head))
        if days:
            last = days[-1]
            description = head[: last.start()].strip()
            if tail and not head[last.end() :].strip():
                rows.append([description, last.group(1), tail.group(1)])
                pending = None
            elif not tail and not line[last.end() :].strip():
                # Data sama w linii (zawinięty opis): godziny na końcu następnej.
                pending = (description, last.group(1))
            continue
        if pending and tail:
            rows.append(
                [
                    f"{pending[0]} {line[: tail.start()]}".strip(),
                    pending[1],
                    tail.group(1),
                ]
            )
            pending = None
    return rows


def _xlsx(content: bytes) -> Optional[ParsedBik]:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            workbook = xlsx.load_workbook(content, data_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.info("timesheet_bik: arkusz nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        for ws in workbook.worksheets:
            if ws.sheet_state != "visible":
                continue
            rows = [
                list(r)
                for r in ws.iter_rows(
                    max_row=min(ws.max_row, MAX_ROWS),
                    max_col=min(ws.max_column, MAX_COLS),
                    values_only=True,
                )
            ]
            hidden = [
                number - 1
                for number, dim in ws.row_dimensions.items()
                if dim.hidden and number >= 1
            ]
            parsed = parse_rows(rows, source="xlsx", hidden_rows=hidden)
            if parsed is not None:
                return parsed
        return None
    finally:
        workbook.close()


def _pdf(content: bytes) -> Optional[ParsedBik]:
    import pdfplumber

    rows: list[list[Any]] = []
    title = False
    text = ""
    quiet = logging.getLogger("pdfminer")
    previous = quiet.level
    # pdfminer loguje każdą czcionkę bez FontBBox (szablon BIK z Calibri).
    quiet.setLevel(logging.ERROR)
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:20]:
                page_text = page.extract_text() or ""
                text += page_text + "\n"
                title = title or bool(_TITLE.search(page_text))
                for found in page.extract_tables():
                    rows.extend(list(r) for r in found)
    except Exception as exc:  # noqa: BLE001
        logger.info("timesheet_bik: PDF nieczytelny (%s)", type(exc).__name__)
        return None
    finally:
        quiet.setLevel(previous)
    if not title:
        return None
    parsed = parse_rows(rows, source="pdf", title=True)
    from_text = parse_rows(text_rows(text), source="pdf", title=True)
    if from_text is None:
        return parsed
    # Tabela bez linii siatki (``extract_tables`` nic nie widzi) albo tabela bez
    # pól „Imię i nazwisko” i „Miesiąc”, które stoją nad nią w tekście strony.
    if (
        parsed is None
        or (not parsed.entries and parsed.declared_total is None)
        or (parsed.month is None and from_text.month is not None)
    ):
        return from_text
    return parsed


def _docx(content: bytes) -> Optional[ParsedBik]:
    """Ten sam szablon w Wordzie (próba VI–VIII 2026): akapity z polami nad tabelą
    „Zadanie · Data · Czas (godz.)” i wiersz „Suma”. Czytamy go jak tekst PDF."""

    text = docx_text(content)
    if not text or not _TITLE.search(text):
        return None
    lines = (" ".join(part for part in line.split(" | ")) for line in text.splitlines())
    return parse_rows(text_rows("\n".join(lines)), source="docx", title=True)


def parse(content: bytes, mime: str) -> Optional[ParsedBik]:
    if mime == XLSX:
        return _xlsx(content)
    if mime == PDF:
        return _pdf(content)
    if mime == DOCX:
        return _docx(content)
    return None


def is_blank(content: bytes, mime: str) -> bool:
    """Szablon bez godzin i bez sumy: wzór, nie raport (wybór pliku miesiąca)."""

    parsed = parse(content, mime)
    return (
        parsed is not None
        and not parsed.entries
        and not (parsed.declared_total or Decimal("0")) > 0
    )


def template_dates_month(parsed: ParsedBik, month: str) -> Optional[str]:
    """Miesiąc z dat wierszy, gdy daty zostały z szablonu (BIK, próba VII 2026:
    daty z lipca 2025 w raporcie za lipiec 2026, MD równe fakturze): pole „Miesiąc”
    to rozliczany miesiąc, wszystkie wiersze mają daty z jednego innego miesiąca,
    a dni z godzinami to dni robocze rozliczanego miesiąca, nie tamtego. ``None``
    = brak dowodu (wiersz bez daty, daty z dwóch miesięcy, inne pole „Miesiąc”,
    dni pasujące do obu kalendarzy)."""

    if parsed.month != month or not parsed.entries:
        return None
    days = [entry.day for entry in parsed.entries]
    if any(day is None for day in days):
        return None
    months = {f"{day.year}-{day.month:02d}" for day in days if day is not None}
    if len(months) != 1 or months == {month}:
        return None
    (template,) = months
    worked = (day.day for day in days if day is not None)
    return template if template_month.days_fit(worked, month, template) else None


def evaluate(
    parsed: ParsedBik,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
    file_name: Optional[str] = None,
) -> ProofResult:
    """Kontrole raportu z katalogu reguł; MD = godziny / ``fields.md_hours``.

    ``file_name``: nazwa pliku; raport bez pola „Imię i nazwisko” bierze osobę
    z niej (jak Time Sheet, ``timesheet.evaluate``)."""

    result = ProofResult(md_regular=None, md_extra=None)
    sheet = _Group(result, rules, GROUP_TITLE)
    hours = parsed.total_hours
    per_md = _param_dec(rules, "fields.md_hours", "hours", "8")
    per_md = per_md if per_md > 0 else Decimal("8")

    if hours <= 0:
        sheet.info(
            "Raport godzin bez godzin",
            "Nie ma wierszy z godzinami ani sumy. MD wpisują Finanse; plik "
            "zostaje w NEXUS-ie.",
        )
        result.warn = True
        sheet.close()
        return result

    result.md_regular = md_from_hours(hours, per_md)
    result.md_extra = Decimal("0")

    found = parsed.month or parsed.entries_month()
    if found == month:
        where = "z pola „Miesiąc”" if parsed.month else "z dat wierszy"
        sheet.ok(f"Miesiąc {where}: {month_label(month)}")
    elif found is not None:
        month_mismatch(
            sheet, "Raport godzin za inny miesiąc", f"W pliku: {month_label(found)}."
        )
    else:
        sheet.fail(
            "proof.month", "Raport godzin za inny miesiąc", "W pliku: brak miesiąca."
        )
    outside = [
        e
        for e in parsed.entries
        if e.day is not None and f"{e.day.year}-{e.day.month:02d}" != month
    ]
    template = template_dates_month(parsed, month) if outside else None
    if template is not None:
        sheet.note(
            f"Wiersze z datą spoza miesiąca: {len(outside)}",
            f"Daty z szablonu: {month_label(template)}. Pole „Miesiąc” i dni "
            f"z godzinami wskazują {month_label(month)}: liczymy jako rozliczany "
            f"miesiąc ({_fmt(hours)} h).",
            code=NOTE_ROW_DATES,
        )
    elif outside:
        sheet.warn(
            f"Wiersze z datą spoza miesiąca: {len(outside)}",
            f"Razem {_fmt(sum((e.hours for e in outside), Decimal('0')))} h, "
            "liczone do MD.",
        )

    consultant = name_tokens(parsed.consultant)
    person = name_tokens(person_name)
    if consultant and person and (consultant <= person or person <= consultant):
        sheet.ok("Imię i nazwisko jak w kontrakcie")
    elif consultant:
        sheet.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    elif len(person) > 1 and person <= _file_words(file_name):
        # Próba VI–VIII 2026: arkusz BIK bez pola z osobą, osoba w nazwie pliku.
        sheet.ok(
            "Imię i nazwisko z nazwy pliku jak w kontrakcie",
            "W raporcie nie ma pola „Imię i nazwisko”.",
        )
    else:
        sheet.fail("proof.name_match", "Raport godzin bez imienia i nazwiska")
    if parsed.order_number:
        sheet.info(f"Numer zamówienia w raporcie: {parsed.order_number}")
    sheet.close()

    sums = _Group(result, rules, "Pola i sumy")
    if sums.on("fields.md_hours"):
        detail = f"{_fmt(hours)} h / {_fmt(per_md)} = {_fmt(result.md_regular)} MD."
        rows = parsed.rows_hours
        if parsed.rows_match_total:
            sums.ok("Godziny policzone od nowa", detail)
        elif parsed.source == "pdf":
            sums.warn(
                "MD z „Sumy godzin”: część wierszy PDF nieczytelna",
                f"Z odczytanych wierszy {_fmt(rows)} h, suma w pliku "
                f"{_fmt(parsed.declared_total)} h. {detail}",
            )
        else:
            sums.fail(
                "fields.md_hours",
                "„Suma godzin” inna niż suma wierszy",
                f"W pliku {_fmt(parsed.declared_total)} h, z wierszy {_fmt(rows)} h. "
                f"{detail}",
            )
    if parsed.hidden_hours > 0:
        sums.warn(
            f"Ukryte wiersze z godzinami: {_fmt(parsed.hidden_hours)} h",
            "Liczymy je, tak jak wzór sumy w Excelu.",
        )
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
    if found is not None and found != month:
        result.md_regular = None
        result.md_extra = None
    return result
