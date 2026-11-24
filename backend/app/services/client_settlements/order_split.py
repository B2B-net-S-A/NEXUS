"""Podział rozliczenia osoby na zamówienia według maila klienta. Bez bazy.

Próba IX–X 2026: klient prosi o faktury osobno na każde zamówienie, a NEXUS
liczył miesiąc osoby na jednym zamówieniu (``service._order_for``), więc
„Do faktury” nie zgadzało się z fakturami Finansów. Dwa wzory z poczty rozliczeń:

* ``lines`` (BIK, X 2026): w odpowiedzi na naszą prośbę o akceptację godzin
  klient pisze „Akceptuję. Prośba o rozliczenie października według zamówień:”
  i linie „<numer>: 48h  4800,00 PLN”. Liczy się liczba z jednostką (h, godz.,
  godzin, MD) zaraz po numerze; kwota za nią nie ma znaczenia, bo stawkę bierzemy
  z zamówienia. Czytamy pierwszą wiadomość wątku z takimi liniami: cytaty niżej
  mają nieaktualne liczby. Ten sam numer dwa razy w tej wiadomości = brak podziału.
* ``table`` (Polkomtel, IX 2026): koordynatorka klienta wkleja tabelę przestawną
  Excela — nagłówek „Etykiety wierszy” i numery SAP, wiersz = osoba („Nazwisko
  Imię”), komórki z MD albo puste. Tekst maila gubi puste komórki („6 2,5 13,5”
  przy czterech kolumnach), więc tabelę czytamy tylko z HTML. Wiersz i kolumna
  sum („Suma końcowa”) nie są ani osobą, ani zamówieniem.

``author`` to nadawca wiadomości z podziałem; przy przekazaniu dalej nadawca
z cytatu nad tabelą, żeby rozliczenie przyjęło podział tylko od klienta. Czytnik
nie zna kontraktów: osobę z wiersza i zamówienia osoby dopasowuje rozliczenie
(``row_for``, ``order_key``), a jednostkę liczb z tabeli — z MD rozliczenia.
"""

from __future__ import annotations

import email
import email.policy
import io
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from email.message import EmailMessage
from html.parser import HTMLParser
from typing import Any, Optional

from app.services.client_settlements import mail_text, timesheet_plus
from app.services.client_settlements.declared import month_in, number, short_lines
from app.services.client_settlements.rcp_checks import name_tokens

logger = logging.getLogger(__name__)

LINES, TABLE = "lines", "table"
HOURS, MD = "h", "md"
_MAX_ROWS = 200
_MAX_COLS = 40
#: Załączone maile (przekazanie jako załącznik) bierzemy do tej liczby.
_MAX_MESSAGES = 5
#: Więcej niż godzin w miesiącu to kwota, nie praca: taka tabela nie jest podziałem.
_MAX_VALUE = Decimal("744")
_PR_HTML = "__substg1.0_10130102"

#: „4500011111:  48h  4800,00 PLN”, „SAP 4500011111 - 5 MD”, „nr 4500011111: 12,5 godz.”
_LINE = re.compile(
    r"^[ \t*•·-]*"
    r"(?:(?:sap|nr|po|zam[oó]wieni\w*|zam)\.?[ \t:#]*)*"
    r"(\d{6,12})(?:[ \t]*[:\-–—][ \t]*|[ \t]+)"
    r"(\d{1,4}(?:[.,]\d{1,3})?)[ \t]*"
    r"(h|godz\w*|md)(?!\w)",
    re.IGNORECASE,
)
_ORDER_CELL = re.compile(r"^(?:sap|po|nr)?[ \t.:#]*\d{6,12}$", re.IGNORECASE)
_TOTAL = re.compile(
    r"^(?:suma(?:\s+ko[nń]cowa)?|grand\s+total|total|razem|og[oó][lł]em)$",
    re.IGNORECASE,
)
_DASH = re.compile(r"^[-–—]$")


@dataclass(frozen=True)
class Part:
    #: Numer zamówienia jak w mailu, bez spacji.
    order: str
    value: Decimal
    #: ``h``, ``md`` albo ``None`` (tabela bez jednostki).
    unit: Optional[str]


@dataclass(frozen=True)
class Row:
    #: ``None``: linie o jednej osobie (osoba z dokumentu, wzór BIK).
    person: Optional[str]
    parts: tuple[Part, ...]


@dataclass(frozen=True)
class Split:
    kind: str
    rows: tuple[Row, ...]
    #: ``RRRR-MM`` z tematu, a bez niego z wiadomości z podziałem.
    month: Optional[str]
    subject: str
    #: Nadawca wiadomości, w której stoi podział.
    author: str
    #: Słowo akceptacji w tej samej wiadomości co podział.
    approved: bool


#: „PO 4500011111” (purchase order) — przedrostka ``timesheet_plus`` nie zdejmuje.
_PO_PREFIX = re.compile(r"^\s*PO(?=[\s.:#]*\d)", re.IGNORECASE)


def order_key(number_text: Optional[str]) -> Optional[str]:
    """„SAP 4500011111”, „PO 4500011111” i „4500011111” to ten sam numer zamówienia."""

    return timesheet_plus.order_key(_PO_PREFIX.sub("", number_text or ""))


def total(row: Row) -> Decimal:
    return sum((part.value for part in row.parts), Decimal("0"))


def author_address(split: Split) -> str:
    """Sam adres autora podziału: „Imię Nazwisko <adres>” → „adres”."""

    found = mail_text._ADDRESS.search(split.author or "")
    return found.group(0).lower() if found else ""


def row_for(split: Split, person_name: str) -> Optional[Row]:
    """Wiersz osoby: linie mówią o jednej osobie, tabela ma wiersz z jej imieniem
    i nazwiskiem w dowolnej kolejności. Dwa takie wiersze = ``None``."""

    if split.kind == LINES:
        return split.rows[0] if len(split.rows) == 1 else None
    wanted = name_tokens(person_name)
    if not wanted:
        return None
    mine = [row for row in split.rows if name_tokens(row.person) == wanted]
    return mine[0] if len(mine) == 1 else None


# ── Linie w treści ───────────────────────────────────────────────────────────


def parse_lines(text: str) -> tuple[Part, ...]:
    """Linie „<numer>: <liczba> h|MD” jednej wiadomości; numer dwa razy = ``()``.

    Linie cytatu z „>” nie liczą się: to starsza wiadomość."""

    parts: list[Part] = []
    for line in short_lines(text).splitlines():
        found = _LINE.match(line)
        value = number(found.group(2)) if found else None
        if found is None or value is None or value <= 0:
            continue
        unit = MD if found.group(3).lower() == MD else HOURS
        parts.append(Part(found.group(1), value, unit))
    keys = [order_key(part.order) for part in parts]
    return () if len(set(keys)) != len(keys) else tuple(parts)


def _own_text(text: str) -> str:
    return "\n".join(
        line for line in text.splitlines() if not mail_text._HEADER_LINE.match(line)
    )


def _lines_split(
    subject: str, sender: str, text: str
) -> tuple[bool, Optional[tuple[Row, str, bool, str]]]:
    """(czy wątek ma linie podziału, (wiersz, autor, akceptacja, tekst wiadomości))."""

    thread = mail_text._messages(
        mail_text.Mail(subject=subject, sender=sender, body=text)
    )
    for author, chunk in thread:
        if not any(_LINE.match(line) for line in short_lines(chunk).splitlines()):
            continue
        parts = parse_lines(chunk)
        if not parts:
            # Pierwsza wiadomość z liniami jest niejednoznaczna; starszych nie bierzemy.
            return True, None
        own = _own_text(chunk)
        approved = bool(mail_text._APPROVED.search(own))
        return True, (Row(None, parts), author or "", approved, own)
    return False, None


# ── Tabela przestawna w HTML ─────────────────────────────────────────────────


@dataclass
class _Table:
    start: int
    end: int = -1
    rows: list[list[str]] = field(default_factory=list)
    cell: Optional[list[str]] = None
    #: Ponad ``_MAX_ROWS`` wierszy dalszych nie zbieramy.
    full: bool = False

    def close_cell(self) -> None:
        if self.cell is not None and self.rows:
            self.rows[-1].append(" ".join("".join(self.cell).split()))
        self.cell = None


class _Tables(HTMLParser):
    """Tabele HTML (też zagnieżdżone) jako wiersze tekstów komórek i ich miejsce
    w źródle; bez stylów i skryptów."""

    def __init__(self, source: str) -> None:
        super().__init__(convert_charrefs=True)
        self.source = source
        self.tables: list[_Table] = []
        self._open: list[_Table] = []
        self._skip = 0
        self._lines = [0] + [m.end() for m in re.finditer("\n", source)]

    def _offset(self) -> int:
        line, column = self.getpos()
        return self._lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, Any]]) -> None:
        if tag in ("style", "script"):
            self._skip += 1
        elif tag == "table":
            self._open.append(_Table(start=self._offset()))
        elif self._open:
            table = self._open[-1]
            if tag == "tr":
                table.close_cell()
                table.full = table.full or len(table.rows) >= _MAX_ROWS
                if not table.full:
                    table.rows.append([])
            elif tag in ("td", "th"):
                table.close_cell()
                if table.rows and not table.full and len(table.rows[-1]) < _MAX_COLS:
                    table.cell = []

    def handle_endtag(self, tag: str) -> None:
        if tag in ("style", "script"):
            self._skip = max(0, self._skip - 1)
        elif self._open and tag in ("td", "th", "tr"):
            self._open[-1].close_cell()
        elif self._open and tag == "table":
            table = self._open.pop()
            table.close_cell()
            closing = self.source.find(">", self._offset())
            table.end = len(self.source) if closing < 0 else closing + 1
            self.tables.append(table)

    def handle_data(self, data: str) -> None:
        if not self._skip and self._open and self._open[-1].cell is not None:
            self._open[-1].cell.append(data)

    def finish(self) -> list[_Table]:
        self.close()
        while self._open:
            table = self._open.pop()
            table.close_cell()
            table.end = len(self.source)
            self.tables.append(table)
        return sorted(self.tables, key=lambda t: t.start)


def _value(cell: str) -> Optional[Decimal]:
    """Liczba z komórki; pusta albo „-” = 0, tekst = ``None``."""

    if not cell or _DASH.match(cell):
        return Decimal("0")
    return number(cell)


def _pivot(rows: list[list[str]]) -> Optional[tuple[Row, ...]]:
    """Wiersze osób z tabeli, której nagłówek (w pierwszych pięciu wierszach) ma
    po pierwszej komórce same numery zamówień albo kolumny sum."""

    for at, header in enumerate(rows[:5]):
        cells = header[1:]
        orders = {
            index: re.sub(r"\s+", "", cell)
            for index, cell in enumerate(cells, start=1)
            if _ORDER_CELL.match(cell)
        }
        if not orders or any(
            cell and not _ORDER_CELL.match(cell) and not _TOTAL.match(cell)
            for cell in cells
        ):
            continue
        if len({order_key(o) for o in orders.values()}) != len(orders):
            return None  # numer dwa razy w nagłówku: nie wiadomo, która kolumna
        found: list[Row] = []
        for row in rows[at + 1 :]:
            label = row[0] if row else ""
            words = [w for w in name_tokens(label) if w.isalpha()]
            if _TOTAL.match(label) or len(words) < 2:
                continue  # suma, „(puste)” albo wiersz bez imienia i nazwiska
            parts: list[Part] = []
            for index, order in orders.items():
                value = _value(row[index] if index < len(row) else "")
                if value is None or value > _MAX_VALUE:
                    return None  # tekst albo kwota w komórce: to nie tabela MD
                if value > 0:
                    parts.append(Part(order, value, None))
            if parts:
                found.append(Row(label, tuple(parts)))
        return tuple(found) or None
    return None


def _first_table(html: str) -> Optional[tuple[_Table, tuple[Row, ...]]]:
    parser = _Tables(html)
    try:
        parser.feed(html)
        tables = parser.finish()
    except (AssertionError, ValueError):
        return None
    for table in tables:
        rows = _pivot(table.rows)
        if rows:
            return table, rows
    return None


def parse_table(html: str) -> tuple[Row, ...]:
    """Pierwsza tabela przestawna osoba × zamówienie z HTML maila; brak = ``()``."""

    found = _first_table(html)
    return found[1] if found else ()


def _header_sender(line: str) -> Optional[str]:
    """Nadawca z nagłówka cytatu „From:/Od:” z adresem; inna linia = ``None``."""

    head = mail_text._QUOTED_FROM.match(line)
    if head and mail_text._ADDRESS.search(head.group(1)):
        return head.group(1).strip()
    return None


def _table_context(html: str, table: _Table, sender: str) -> tuple[str, bool, str]:
    """Autor, akceptacja i tekst wiadomości, w której stoi tabela: od ostatniego
    nagłówka cytatu „From:/Od:” przed tabelą do następnego za nią."""

    before = mail_text._html_to_text(html[: table.start]).splitlines()
    after = mail_text._html_to_text(html[table.end :]).splitlines()
    author, begin = sender, 0
    for index, line in enumerate(before):
        quoted = _header_sender(line)
        if quoted is not None:
            author, begin = quoted, index + 1
    own = before[begin:]
    for line in after:
        if _header_sender(line) is not None:
            break
        own.append(line)
    text = _own_text("\n".join(own))
    return author, bool(mail_text._APPROVED.search(text)), text


# ── Mail ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class _Message:
    subject: str
    sender: str
    plain: str
    html: str


def _content(message: EmailMessage, kind: str) -> str:
    part = message.get_body(preferencelist=(kind,))
    if part is None:
        return ""
    try:
        return str(part.get_content())[: mail_text.MAX_TEXT]
    except (KeyError, LookupError, ValueError, TypeError):
        return ""


def _eml_messages(content: bytes) -> list[_Message]:
    """Sam mail i maile w nim załączone (``message/rfc822``), w kolejności z pliku."""

    root = email.message_from_bytes(content, policy=email.policy.default)
    found: list[EmailMessage] = [root]  # type: ignore[list-item]
    for part in root.walk():
        if part.get_content_type() != "message/rfc822" or not part.is_multipart():
            continue
        inner = part.get_payload(0)
        if isinstance(inner, EmailMessage) and len(found) < _MAX_MESSAGES:
            found.append(inner)
    return [
        _Message(
            subject=str(m.get("subject") or ""),
            sender=str(m.get("from") or ""),
            plain=_content(m, "plain"),
            html=_content(m, "html"),
        )
        for m in found
    ]


def _msg_html(content: bytes) -> str:
    """Treść HTML ``.msg`` (PR_HTML); brak strumienia = pusty tekst."""

    import olefile

    ole = olefile.OleFileIO(io.BytesIO(content))
    try:
        if not ole.exists(_PR_HTML):
            return ""
        raw = ole.openstream(_PR_HTML).read()
    finally:
        ole.close()
    try:
        return raw.decode("utf-8")[: mail_text.MAX_TEXT]
    except UnicodeDecodeError:
        return raw.decode("cp1250", "replace")[: mail_text.MAX_TEXT]


def _msg_messages(content: bytes) -> list[_Message]:
    mail = mail_text.read(content, mail_text.MSG)
    if mail is None:
        return []
    return [_Message(mail.subject, mail.sender, mail.body, _msg_html(content))]


def _from_messages(messages: list[_Message]) -> Optional[Split]:
    if not messages:
        return None
    subject = messages[0].subject
    for message in messages:
        found = _first_table(message.html) if message.html else None
        if found is None:
            continue
        table, rows = found
        author, approved, text = _table_context(message.html, table, message.sender)
        return Split(
            kind=TABLE,
            rows=rows,
            month=month_in(subject) or month_in(message.subject) or month_in(text),
            subject=subject,
            author=author,
            approved=approved,
        )
    for message in messages:
        text = message.plain or mail_text._html_to_text(message.html)
        seen, found_lines = _lines_split(message.subject, message.sender, text)
        if not seen:
            continue
        if found_lines is None:
            return None
        row, author, approved, own = found_lines
        return Split(
            kind=LINES,
            rows=(row,),
            month=month_in(subject) or month_in(message.subject) or month_in(own),
            subject=subject,
            author=author,
            approved=approved,
        )
    return None


def parse(content: bytes, mime: str) -> Optional[Split]:
    """Podział z ``.eml`` albo ``.msg``; mail bez podziału = ``None``."""

    try:
        if mime == mail_text.EML:
            return _from_messages(_eml_messages(content))
        if mime == mail_text.MSG:
            return _from_messages(_msg_messages(content))
    except Exception as exc:  # noqa: BLE001 — uszkodzony plik nie blokuje rozliczenia
        logger.info("order_split: odczyt nie wyszedł (%s)", type(exc).__name__)
    return None
