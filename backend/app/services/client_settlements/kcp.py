"""Karta ewidencji świadczenia usług (KCP) Banku Pocztowego (roadmapa E6.5). Bez bazy.

KCP to arkusz „KARTA” ze wzoru banku ``Karta_pracy_wzór.xlsm``: konsultant wkleja
do arkusza „import” eksport Redmine „Przepracowany czas”, a „KARTA” składa z niego
nagłówek („Imię i Nazwisko: Nazwisko Imię”, „Miesiąc: Październik”, „Rok: 2026”),
tabelę dni 1–31 (zagadnienia, liczba godzin) i sumy („Suma dni przepracowanych”,
„Liczba godzin czas podstawowy”, „Liczba godzin - nadgodziny”). Do NEXUS-a
przychodzi zwykle PDF tej karty (bez podpisu cyfrowego), czasem sam arkusz.

Podpisu dysponenta nie sprawdzamy (decyzja Artura z 18.11.2026): akceptacją jest
mail banku po zbiorczej wysyłce KCP (``client_acceptance``).

Plik spoza wzoru daje ``None``; odczyt nigdy nie blokuje przyjęcia pliku.
"""

from __future__ import annotations

import io
import logging
import re
import unicodedata
from calendar import monthrange
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Iterable, Mapping, Optional

from app.services.client_settlements import timesheet_pko, xlsx
from app.services.client_settlements.rcp_bnp import _dec
from app.services.client_settlements.rcp_checks import (
    ProofResult,
    _fmt,
    _Group,
    _param_dec,
    name_tokens,
)
from app.services.client_settlements.timesheet import md_from_hours, per_md

logger = logging.getLogger(__name__)

PDF = "application/pdf"
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
XLSM = timesheet_pko.XLSM
TITLE = "karta ewidencji swiadczenia uslug"
GROUP_KCP = "KCP (karta ewidencji świadczenia usług)"
GROUP_REDMINE = "Raport godzin z Redmine"
#: Karta z eksportu Redmine ma po kilka zagadnień dziennie: miesiąc to zwykle
#: 6 stron, a sumy są na ostatniej. Limit tylko chroni przed nie-kartą.
MAX_PAGES = 40
MAX_ROWS = 120
MAX_COLS = 8
#: Miesiąc słownie w mianowniku, jak w arkuszu „slownik” wzoru banku.
MONTHS = (
    "styczen",
    "luty",
    "marzec",
    "kwiecien",
    "maj",
    "czerwiec",
    "lipiec",
    "sierpien",
    "wrzesien",
    "pazdziernik",
    "listopad",
    "grudzien",
)
MONTHS_PL = (
    "Styczeń",
    "Luty",
    "Marzec",
    "Kwiecień",
    "Maj",
    "Czerwiec",
    "Lipiec",
    "Sierpień",
    "Wrzesień",
    "Październik",
    "Listopad",
    "Grudzień",
)


@dataclass(frozen=True)
class KcpDay:
    day: int
    description: str
    hours: Decimal


@dataclass(frozen=True)
class ParsedKcp:
    #: Osoba jak w nagłówku KCP (wzór banku pisze „Nazwisko Imię”).
    person: Optional[str]
    #: ``RRRR-MM`` z „Miesiąc” i „Rok”.
    month: Optional[str]
    days: tuple[KcpDay, ...]
    declared_days: Optional[Decimal] = None
    declared_hours: Optional[Decimal] = None
    overtime_hours: Optional[Decimal] = None
    #: ``kcp`` — karta od konsultanta, ``redmine`` — złożona przez NEXUS z eksportu.
    source: str = "kcp"

    @property
    def total_hours(self) -> Decimal:
        return sum((d.hours for d in self.days), Decimal("0"))

    @property
    def worked_days(self) -> int:
        return sum(1 for d in self.days if d.hours > 0)


def fold(text: Any) -> str:
    raw = unicodedata.normalize(
        "NFKD", str(text or "").replace("ł", "l").replace("Ł", "L")
    )
    return " ".join(raw.encode("ascii", "ignore").decode().lower().split())


def month_number(word: str) -> Optional[int]:
    folded = fold(word)
    for index, name in enumerate(MONTHS, start=1):
        if folded.startswith(name):
            return index
    return None


def _day_number(cell: Any) -> Optional[int]:
    if isinstance(cell, bool):
        return None
    if isinstance(cell, (int, float)) and float(cell).is_integer():
        value = int(cell)
    elif isinstance(cell, str) and re.fullmatch(r"\s*\d{1,2}\s*", cell):
        value = int(cell)
    else:
        return None
    return value if 1 <= value <= 31 else None


def _text(cell: Any) -> str:
    return " ".join(str(cell).split()) if cell is not None else ""


_LABELS = {
    "suma dni przepracowanych": "declared_days",
    "liczba godzin czas podstawowy": "declared_hours",
    "liczba godzin - nadgodziny": "overtime_hours",
}


def _labelled(row: list[Any]) -> Optional[tuple[str, Optional[Decimal]]]:
    """Wiersz sumy: etykieta i liczba w następnej komórce albo na końcu tej samej
    (tekst strony PDF ma etykietę i wartość w jednej linii)."""

    for i, cell in enumerate(row):
        folded = fold(cell)
        for label, key in _LABELS.items():
            if not folded.startswith(label):
                continue
            rest = folded[len(label) :].strip()
            if rest:
                return key, _dec(rest)
            after = next((v for v in row[i + 1 :] if v not in (None, "")), None)
            return key, _dec(after) if after is not None else None
    return None


def parse_rows(rows: Iterable[list[Any]]) -> Optional[ParsedKcp]:
    """Wiersze arkusza „KARTA” albo tabel i linii PDF → KCP. Bez pliku, do testów."""

    titled = False
    person: Optional[str] = None
    mon: Optional[int] = None
    year: Optional[int] = None
    days: dict[int, KcpDay] = {}
    sums: dict[str, Optional[Decimal]] = {}
    for row in rows:
        cells = [c for c in row if c not in (None, "")]
        if not cells:
            continue
        first = fold(cells[0])
        if TITLE in first:
            titled = True
            continue
        if first.startswith("imie i nazwisko:"):
            person = _text(cells[0]).split(":", 1)[1].strip() or person
            continue
        if first.startswith("miesiac:"):
            mon = month_number(first.split(":", 1)[1]) or mon
            continue
        if first.startswith("rok:"):
            found = re.search(r"\d{4}", first)
            year = int(found.group()) if found else year
            continue
        labelled = _labelled(cells)
        if labelled is not None:
            key, value = labelled
            sums.setdefault(key, value)
            continue
        day = _day_number(row[0] if row else None)
        if day is None or len(row) < 2:
            continue
        description = _text(row[1]) if len(row) > 1 else ""
        hours = _dec(row[2]) if len(row) > 2 and row[2] not in (None, "") else None
        if day not in days:
            days[day] = KcpDay(day, description, hours or Decimal("0"))
    if not titled:
        return None
    return ParsedKcp(
        person=person,
        month=f"{year}-{mon:02d}" if year and mon else None,
        days=tuple(days[d] for d in sorted(days)),
        declared_days=sums.get("declared_days"),
        declared_hours=sums.get("declared_hours"),
        overtime_hours=sums.get("overtime_hours"),
    )


def _pdf_rows(content: bytes) -> Optional[list[list[Any]]]:
    import pdfplumber

    rows: list[list[Any]] = []
    try:
        with pdfplumber.open(io.BytesIO(content)) as pdf:
            for page in pdf.pages[:MAX_PAGES]:
                rows.extend([line] for line in (page.extract_text() or "").splitlines())
                for table in page.extract_tables():
                    rows.extend(list(r) for r in table)
    except Exception as exc:  # noqa: BLE001 — zły PDF to nie KCP, a nie awaria
        logger.info("kcp: PDF nieczytelny (%s)", type(exc).__name__)
        return None
    return rows


def _sheet_rows(content: bytes) -> Optional[list[list[Any]]]:
    try:
        workbook = xlsx.load_workbook(content, data_only=True, read_only=True)
    except Exception as exc:  # noqa: BLE001
        logger.info("kcp: arkusz nieczytelny (%s)", type(exc).__name__)
        return None
    try:
        sheets = [ws for ws in workbook.worksheets if fold(ws.title) == "karta"]
        rows: list[list[Any]] = []
        for ws in sheets:
            rows.extend(
                list(r)
                for r in ws.iter_rows(
                    max_row=MAX_ROWS, max_col=MAX_COLS, values_only=True
                )
            )
        return rows
    finally:
        workbook.close()


def parse(content: bytes, mime: str) -> Optional[ParsedKcp]:
    if mime == PDF:
        rows = _pdf_rows(content)
    elif mime in (XLSX, XLSM):
        rows = _sheet_rows(content)
    else:
        return None
    return parse_rows(rows) if rows else None


def evaluate(
    parsed: ParsedKcp,
    *,
    month: str,
    person_name: str,
    rules: Mapping[str, Mapping[str, Any]],
    working_days: int,
    other_md: Decimal = Decimal("0"),
    outside_month: int = 0,
) -> ProofResult:
    """Kontrole KCP z katalogu reguł; MD z godzin, nadgodziny osobno."""

    result = ProofResult(md_regular=None, md_extra=None)
    redmine = parsed.source == "redmine"
    card = _Group(result, rules, GROUP_REDMINE if redmine else GROUP_KCP)
    hours = parsed.total_hours
    hours_md = per_md(rules)
    result.meta["kcp"] = {
        "source": parsed.source,
        "hours": f"{hours:f}",
        "days": parsed.worked_days,
    }
    if hours <= 0 and not parsed.declared_hours:
        card.info(
            "KCP bez godzin",
            "Nie ma dni z godzinami. MD wpisują Finanse; plik zostaje w NEXUS-ie.",
        )
        result.warn = True
        card.close()
        return result
    if hours <= 0 and parsed.declared_hours:
        # Tabela dni nieodczytana (np. inny wydruk): liczymy z sumy karty.
        hours = parsed.declared_hours
        card.warn(
            "Nie odczytano dni z KCP",
            f"MD z sumy karty: {_fmt(hours)} h. Sprawdź plik.",
        )
    result.md_regular = md_from_hours(hours, hours_md)
    overtime = parsed.overtime_hours or Decimal("0")
    result.md_extra = (
        md_from_hours(overtime, hours_md) if overtime > 0 else Decimal("0")
    )

    if parsed.month == month:
        card.ok(f"Miesiąc z KCP: {month}")
    else:
        card.fail(
            "proof.month",
            "KCP za inny miesiąc",
            f"Na karcie: {parsed.month or 'brak miesiąca i roku'}.",
        )
    if (
        not redmine
        and parsed.days
        and parsed.declared_days is None
        and parsed.declared_hours is None
    ):
        card.warn(
            "Nie odczytano sum z KCP",
            "Brak „Suma dni przepracowanych” i „Liczba godzin czas podstawowy”;"
            " dni mogły się nie odczytać w całości. Sprawdź plik.",
        )
    if outside_month:
        card.fail(
            "proof.month",
            f"Wpisy spoza rozliczanego miesiąca: {outside_month}",
            "Nie weszły do KCP; sprawdź daty w Redmine.",
        )
    on_card = name_tokens(parsed.person)
    person = name_tokens(person_name)
    if on_card and person and (on_card <= person or person <= on_card):
        card.ok("Imię i nazwisko jak w kontrakcie")
    elif on_card:
        card.fail("proof.name_match", "Inne imię lub nazwisko niż w kontrakcie")
    else:
        card.fail(
            "proof.name_match",
            "KCP bez imienia i nazwiska"
            if not redmine
            else "Raport bez użytkownika Redmine",
        )
    if redmine:
        card.ok(
            "KCP złożona przez NEXUS ze wzoru banku",
            "Ten sam układ co arkusz „KARTA”: dni, zagadnienia, godziny i sumy.",
        )
    card.close()

    sums = _Group(result, rules, "Pola i sumy")
    if sums.on("fields.md_hours"):
        detail = f"{_fmt(hours)} h / {_fmt(hours_md)} = {_fmt(result.md_regular)} MD."
        declared = parsed.declared_hours
        if (
            declared is not None
            and abs(declared - parsed.total_hours) > Decimal("0.01")
            and parsed.days
        ):
            sums.fail(
                "fields.md_hours",
                "Suma godzin na KCP inna niż suma dni",
                f"Na karcie {_fmt(declared)} h, z dni {_fmt(parsed.total_hours)} h. {detail}",
            )
        else:
            sums.ok(f"{parsed.worked_days} dni, {_fmt(hours)} h", detail)
        if (
            parsed.declared_days is not None
            and parsed.days
            and parsed.declared_days != parsed.worked_days
        ):
            sums.fail(
                "fields.md_hours",
                "Liczba dni na KCP inna niż dni z godzinami",
                f"Na karcie {_fmt(parsed.declared_days)}, z tabeli {parsed.worked_days}.",
            )
    if overtime > 0:
        sums.info(
            f"Nadgodziny: {_fmt(overtime)} h",
            f"{_fmt(result.md_extra)} MD jako praca dodatkowa.",
        )
    if sums.on("fields.day_limit") and parsed.days:
        limit = _param_dec(rules, "fields.day_limit", "hours", "24")
        worst = max(parsed.days, key=lambda d: d.hours)
        if worst.hours <= limit:
            sums.ok(
                f"Najwięcej w jednym dniu: {_fmt(worst.hours)} h",
                f"Limit {_fmt(limit)} h.",
            )
        else:
            sums.fail(
                "fields.day_limit",
                f"{_fmt(worst.hours)} h w dniu {worst.day}",
                f"Limit {_fmt(limit)} h.",
            )
    blank = [d.day for d in parsed.days if d.hours > 0 and not d.description]
    if blank:
        sums.warn(
            "Dni z godzinami bez zagadnienia: " + ", ".join(str(d) for d in blank),
            "Wzór banku oznacza je na czerwono; zagadnienie poprawia się w Redmine.",
        )
    if parsed.month:
        year, mon = (int(x) for x in parsed.month.split("-"))
        beyond = [d.day for d in parsed.days if d.day > monthrange(year, mon)[1]]
        if beyond and any(d.hours > 0 for d in parsed.days if d.day in beyond):
            sums.warn(f"Godziny w dniu spoza miesiąca: {', '.join(map(str, beyond))}")
    timesheet_pko.month_limit(sums, result.md_regular, working_days, other_md)
    sums.close()
    return result
