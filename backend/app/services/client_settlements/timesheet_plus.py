"""Raporty godzin grupy Polkomtel / Cyfrowy Polsat (próba IX–X 2026).

Bez bazy. Oba pliki mają rozszerzenie ``.xls``, ale żaden nie jest starym Excelem:

* Polkomtel: „Project timesheet Report” z Jiry klienta, tabela HTML. Nagłówek
  „Nazwisko konsultanta”, „Miesiąc” („Wrzesień 2026”), „Nr zlecenia” (w archiwum
  pusty w 81 z 82 plików), „Suma godzin” („176 godz.”), potem dni „DD/MM/RRRR”
  z godzinami. Konsultant przekazuje go ze skrzynki firmowej z fakturą.
* Cyfrowy Polsat: „B2B_RRRR_MM.xls”, XML Spreadsheet 2003. Wiersz = konsultant
  („Nazwisko Imię”) × zamówienie (``Z990101001``); kolumna miesiąca w godzinach,
  obok godziny dni 1–31. Kierowniczka u klienta przysyła go z ``plus.pl``.
  Ten sam układ przychodzi też jako prawdziwy ``.xlsx`` („B2B czerwiec 2026.xlsx”,
  „B2B_2026_07.xlsx”, próba VI–VIII 2026), czasem bez kolumn „R(h)”/„P(h)”, i niesie
  wiersze kilku osób albo jednej osoby na zamówieniach Polsatu i Polkomtelu — wtedy
  plik dostaje każdy rozpoznany kontrakt (``identity.resolve_sheet_contracts``,
  ``consultant_portal.mailbox``), a godziny kontraktu to wiersze jego zamówień
  (``declared_for(orders=…)``).

Konsultanci grupy mają kontrakt w każdej spółce (ta sama data startu, zamówienia
osobno), więc nadawca nie wskazuje kontraktu, a plik tak: numer zamówienia z wiersza,
a raport Polkomtelu bez numeru należy do kontraktu u Polkomtelu (decyzja Artura
z 23.11.2026; wybór kontraktu w ``consultant_portal.identity``).

MD = godziny / ``fields.md_hours`` (``declared``). Suma z nagłówka inna niż suma
dni albo kolumna miesiąca inna niż dni = brak godzin: nie zgadujemy, który zapis
jest dobry, MD wpisują Finanse.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Optional

from app.services.client_settlements import kesu, xlsx
from app.services.client_settlements.declared import Declared, month_in
from app.services.client_settlements.mail_text import _month_index
from app.services.client_settlements.rcp_checks import name_tokens

POLKOMTEL = "polkomtel"
POLSAT = "polsat"
LABELS = {
    POLKOMTEL: "Raport godzin Polkomtelu",
    POLSAT: "Rozliczenie Cyfrowego Polsatu",
}
#: 31 dni + opis, dostawca, konsultant, zamówienie, R(h), P(h), miesiąc.
_POLSAT_COLS = 64
_MAX_HTML_ROWS = 400
_HTML_TITLE = re.compile(
    rb"<title>\s*project\s+timesheet\s+report\s*</title>", re.IGNORECASE
)
_HOURS = re.compile(r"^\s*(\d{1,3}(?:[.,]\d{1,2})?)\s*(?:godz\.?|h)?\s*$", re.I)
_DAY = re.compile(r"^\s*\d{1,2}[./]\d{1,2}[./]20\d{2}\s*$")
_ORDER_PREFIX = re.compile(r"^(?:CP|SAP|NR)(?=[0-9Z])")


@dataclass(frozen=True)
class Row:
    person: str
    order: Optional[str]
    #: ``None``, gdy sumy w pliku się nie zgadzają.
    hours: Optional[Decimal]


@dataclass(frozen=True)
class Sheet:
    source: str
    #: ``RRRR-MM`` z pliku.
    month: Optional[str]
    rows: tuple[Row, ...]


def order_key(number: Optional[str]) -> Optional[str]:
    """Numer zamówienia bez spacji i przedrostka spółki: „CP Z990101001” i
    „Z990101001” to to samo zamówienie, „SAP 4500000001” i „4500000001” też."""

    cleaned = re.sub(r"[^0-9A-Z]", "", (number or "").upper())
    cleaned = _ORDER_PREFIX.sub("", cleaned)
    return cleaned or None


def _hours(text: Optional[str]) -> Optional[Decimal]:
    found = _HOURS.match(text or "")
    if not found:
        return None
    try:
        return Decimal(found.group(1).replace(",", "."))
    except InvalidOperation:
        return None


# ── Polkomtel: tabela HTML ────────────────────────────────────────────────────


def is_polkomtel_report(content: bytes) -> bool:
    head = content[:4096].lstrip(b"\xef\xbb\xbf \t\r\n")
    return head[:5].lower() == b"<html" and bool(_HTML_TITLE.search(head))


class _Cells(HTMLParser):
    """Wiersze tabeli jako listy tekstów komórek; bez stylów i skryptów."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[str]] = []
        self._cell: Optional[list[str]] = None
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: list) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "tr" and len(self.rows) < _MAX_HTML_ROWS:
            self.rows.append([])
        elif tag in ("td", "th") and self.rows:
            self._cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif tag in ("td", "th") and self._cell is not None:
            self.rows[-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data: str) -> None:
        if self._cell is not None and not self._skip:
            self._cell.append(data)


def _parse_polkomtel(content: bytes) -> Optional[Sheet]:
    parser = _Cells()
    try:
        parser.feed(content.decode("utf-8", "replace"))
        parser.close()
    except (AssertionError, ValueError):
        return None
    fields: dict[str, str] = {}
    days: list[Optional[Decimal]] = []
    for cells in parser.rows:
        if not cells:
            continue
        label = cells[0].lower().rstrip(":").strip()
        if len(cells) > 1 and cells[0].endswith(":"):
            fields.setdefault(label, cells[1])
        elif _DAY.match(cells[0]) and len(cells) > 1:
            days.append(_hours(cells[1]))
    person = fields.get("nazwisko konsultanta", "").strip()
    if not person:
        return None
    total = _hours(fields.get("suma godzin"))
    if days and (None in days or sum(days, Decimal("0")) != total):
        total = None
    return Sheet(
        source=POLKOMTEL,
        month=month_in(fields.get("miesiąc", "")),
        rows=(Row(person, (fields.get("nr zlecenia") or "").strip() or None, total),),
    )


# ── Cyfrowy Polsat: XML Spreadsheet 2003 ──────────────────────────────────────


def _parse_polsat(content: bytes) -> Optional[Sheet]:
    grid = kesu._grid(content, max_cols=_POLSAT_COLS)
    if not grid:
        return None
    return _polsat_rows([{c: v[0].strip() for c, v in row.items()} for row in grid])


def _cell_text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return str(value).strip()


def _parse_polsat_xlsx(content: bytes) -> Optional[Sheet]:
    """Ten sam układ w ``.xlsx`` (próba VI–VIII 2026)."""

    try:
        workbook = xlsx.load_workbook(content, read_only=True, data_only=True)
    except Exception:  # noqa: BLE001 — obcy plik nie jest arkuszem Polsatu
        return None
    try:
        for sheet in workbook.worksheets:
            texts = [
                {
                    column: text
                    for column, value in enumerate(row)
                    if (text := _cell_text(value))
                }
                for row in sheet.iter_rows(
                    max_row=_MAX_HTML_ROWS, max_col=_POLSAT_COLS, values_only=True
                )
            ]
            found = _polsat_rows(texts)
            if found is not None:
                return found
        return None
    except (TypeError, ValueError, KeyError, AttributeError):
        return None
    finally:
        workbook.close()


def _polsat_rows(texts: list[dict[int, str]]) -> Optional[Sheet]:
    """Wiersze osób × zamówień z siatki tekstów komórek (XML 2003 albo XLSX)."""

    header_at = next(
        (
            i
            for i, row in enumerate(texts[:10])
            if {"konsultant", "zamówienie"} <= {v.lower() for v in row.values()}
        ),
        None,
    )
    if header_at is None:
        return None
    header = {v.lower(): c for c, v in texts[header_at].items()}
    person_col, order_col = header["konsultant"], header["zamówienie"]
    # Pod nagłówkiem: wiersz nazw miesięcy i wiersz numerów dni. Kolumna
    # z miesiącem, nad którą nie stoi numer dnia, to suma godzin miesiąca.
    month_row = texts[header_at + 1] if header_at + 1 < len(texts) else {}
    day_row = texts[header_at + 2] if header_at + 2 < len(texts) else {}
    day_cols = {c for c, v in day_row.items() if v.isdigit() and 1 <= int(v) <= 31}
    month_cols = [c for c in month_row if c not in day_cols]
    months = {_month_index(month_row[c]) for c in month_row} - {None}
    years = {v for c, v in texts[header_at].items() if re.fullmatch(r"20\d{2}", v)}
    if not day_cols or len(month_cols) != 1 or len(months) != 1 or len(years) != 1:
        return None
    month = f"{years.pop()}-{months.pop():02d}"
    month_col = month_cols[0]
    rows: list[Row] = []
    for row in texts[header_at + 3 :]:
        person = row.get(person_col, "")
        if not person:
            continue
        per_day = [_hours(row[c]) for c in day_cols if row.get(c)]
        in_month = _hours(row.get(month_col)) if row.get(month_col) else None
        hours: Optional[Decimal]
        if None in per_day:
            hours = None
        else:
            from_days = sum(per_day, Decimal("0"))
            hours = from_days if in_month in (None, from_days) else None
        rows.append(Row(person, row.get(order_col) or None, hours))
    return Sheet(source=POLSAT, month=month, rows=tuple(rows)) if rows else None


def parse(content: bytes) -> Optional[Sheet]:
    """Raport Polkomtelu albo rozliczenie Polsatu; inny plik = ``None``."""

    if is_polkomtel_report(content):
        return _parse_polkomtel(content)
    if kesu.is_kesu_file(content):
        return _parse_polsat(content)
    if content.startswith(b"PK\x03\x04"):
        return _parse_polsat_xlsx(content)
    return None


def people(sheet: Sheet) -> list[set[str]]:
    """Osoby z pliku (tokeny imienia i nazwiska), bez powtórzeń."""

    found: list[set[str]] = []
    for row in sheet.rows:
        tokens = name_tokens(row.person)
        if tokens and tokens not in found:
            found.append(tokens)
    return found


def declared_for(
    sheet: Sheet, person_name: str, *, orders: frozenset[str] = frozenset()
) -> Optional[Declared]:
    """Godziny osoby z kontraktu; plik jednej innej osoby idzie w całości, żeby
    kontrola nazwiska pokazała różnicę zamiast cichego „bez MD”.

    ``orders``: klucze numerów zamówień kontraktu (``order_key``). Gdy któryś wiersz
    osoby ma numer z tego zbioru, liczą się tylko takie wiersze: ta sama osoba ma
    w pliku zamówienia drugiego kontraktu (Polsat i Polkomtel, próba VI–VIII 2026)."""

    wanted = name_tokens(person_name)
    mine = [r for r in sheet.rows if name_tokens(r.person) == wanted]
    if not mine:
        if len(people(sheet)) != 1:
            return None
        mine = list(sheet.rows)
    own = [r for r in mine if order_key(r.order) in orders]
    if own:
        mine = own
    hours: Optional[Decimal] = None
    if all(r.hours is not None for r in mine):
        hours = sum((r.hours for r in mine if r.hours is not None), Decimal("0"))
    return Declared(
        source=LABELS[sheet.source],
        consultant=mine[0].person,
        month=sheet.month,
        hours=hours,
    )
