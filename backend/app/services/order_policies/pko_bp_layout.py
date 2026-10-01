"""PKO BP — tabela Wykonawców odczytana z POŁOŻENIA słów, nie z linii tekstu.

Zwykły tekst z pdfplumbera składa wiersz tabeli w jedną linię i gubi granice
kolumn. Komórki są wyśrodkowane w pionie, więc środkowa linia wielolinijkowego
profilu („Inżynier / DevSecOpS / Senior") ląduje w linii wiersza i skleja się
z nazwiskiem: „Konrad Różycki DevSecOpS 2026-10-01 …" (ticket 12, 10.2026).
Słownik słów profilu nie zna każdego profilu, więc granicę wyznaczamy
geometrycznie:

1. **Kolumny z nagłówków.** Szukamy nagłówków „Imię i nazwisko Wykonawców",
   „Profil", „Początek Zaangażowania", „Planowany Koniec Zaangażowania",
   „Liczba MD", „Stawka PLN/MD netto", „Lokalizacja", „Numer SSGW". Granica
   dwóch kolumn leży w odstępie między ich nagłówkami — w najszerszym pasie
   tego odstępu, którego nie przecina żadne słowo tabeli (linie tabeli nie są
   do tego potrzebne).
2. **Wiersze z dat.** Każda osoba ma dokładnie jedną datę w kolumnie
   „Początek Zaangażowania"; jej środek w pionie to środek wiersza.
3. **Komórki wielolinijkowe.** W każdej kolumnie linie dzielimy na ciągłe
   grupy i przypisujemy wierszom programowaniem dynamicznym: środek grupy
   (komórka wyśrodkowana) albo jej góra (komórka do góry) ma wypaść na wiersz.
   Linia, która do żadnego wiersza nie pasuje (stopka strony), jest pomijana.

Wynik nie jest zgadywany: wiersz bez nazwiska, dat albo czytelnych liczb ma
powód niepewności, a tabela, której nie da się odczytać z położenia, zostawia
tekst bez zmian — wtedy działa dotychczasowa reguła tekstowa (``pko_bp``).

Wynik trafia do TEKSTU dokumentu (``render_table``) w miejsce surowej tabeli,
więc model, reguła, bramka automatu i „Przelicz plan" czytają te same wiersze.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from statistics import median
from typing import Iterable, Optional, Sequence

from app.services.order_policies._shared import clean_person_name, fold

#: Kolumny tabeli Wykonawców w kolejności od lewej.
COLUMNS = ("name", "profile", "start", "end", "md", "rate", "location", "ssgw")

#: Słowo nagłówka (po ``fold``) → kolumna. Każda kolumna musi mieć co najmniej
#: jedno słowo z tej listy, inaczej tabela nie jest tabelą PKO BP.
_HEADER_KEYS: dict[str, tuple[str, ...]] = {
    "name": ("wykonawcow", "imie", "nazwisko"),
    "profile": ("profil",),
    "start": ("poczatek",),
    "end": ("planowany", "koniec"),
    "md": ("liczba",),
    "rate": ("stawka", "pln/md"),
    "location": ("lokalizacja",),
    "ssgw": ("ssgw",),
}

#: Wszystkie słowa nagłówka tabeli (po ``fold``) — także te, które nie
#: wyznaczają kolumny, ale zajmują linie nagłówka.
_HEADER_VOCAB = frozenset(
    {key for keys in _HEADER_KEYS.values() for key in keys}
    | {"i", "zaangazowania", "md", "pln", "netto", "brutto", "numer", "/md"}
)

#: Etykiety kolumn w tekście, który dostaje model i reguła.
LABELS = {
    "name": "Imię i nazwisko Wykonawców",
    "profile": "Profil",
    "start": "Początek Zaangażowania",
    "end": "Planowany Koniec Zaangażowania",
    "md": "Liczba MD",
    "rate": "Stawka PLN/MD netto",
    "location": "Lokalizacja",
    "ssgw": "Numer SSGW",
}

TABLE_TITLE = "Tabela Wykonawców (kolumny odczytane z układu PDF):"
ROW_PREFIX = "Wykonawca"

_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DIGIT_RE = re.compile(r"\d")
# Koniec tabeli: łączna wartość zamówienia albo przypis („* stawka negocjowana").
_END_WORDS = ("laczna",)

REASON_NAME = (
    "Nie odczytano imienia i nazwiska z kolumny „Imię i nazwisko Wykonawców” "
    "— sprawdź osobę"
)
REASON_NAME_CELL = (
    "Kolumna „Imię i nazwisko Wykonawców” w tym wierszu nie układa się "
    "jednoznacznie — sprawdź osobę"
)
REASON_DATES = "Nie odczytano dat zaangażowania w wierszu tabeli — sprawdź okres"
REASON_NUMBERS = (
    "Nie odczytano liczby MD albo stawki w wierszu tabeli — wpisz obie wartości z PDF-a"
)


@dataclass(frozen=True)
class Word:
    page: int
    x0: float
    x1: float
    top: float
    bottom: float
    text: str

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def cy(self) -> float:
        return (self.top + self.bottom) / 2

    @property
    def height(self) -> float:
        return max(self.bottom - self.top, 0.1)

    @property
    def key(self) -> str:
        return fold(self.text).strip(",;:.()")


@dataclass
class LayoutRow:
    """Jeden wiersz tabeli: tekst komórek + powody niepewności."""

    cells: dict[str, str] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)


@dataclass
class LayoutTable:
    rows: list[LayoutRow]
    #: Nagłówek kolumny stawki tak, jak stoi w PDF-ie („Stawka PLN/MD netto");
    #: jawne „brutto" ma dotrzeć do reguły rodzaju stawki.
    rate_label: str


@dataclass
class _Header:
    page: int
    top: float
    bottom: float
    #: Lewa/prawa krawędź tekstu nagłówka każdej kolumny.
    extents: dict[str, tuple[float, float]]
    rate_label: str


def words_from_payload(payload: Optional[Iterable]) -> list[Word]:
    """Słowa z wyniku procesu odczytu PDF (``[strona, x0, x1, góra, dół, tekst]``)."""
    words: list[Word] = []
    for item in payload or ():
        try:
            page, x0, x1, top, bottom, text = item
            words.append(
                Word(
                    int(page),
                    float(x0),
                    float(x1),
                    float(top),
                    float(bottom),
                    str(text),
                )
            )
        except (TypeError, ValueError):
            continue
    return words


# ── Nagłówek ────────────────────────────────────────────────────────────────


def _find_header(page_words: Sequence[Word]) -> Optional[_Header]:
    """Nagłówek tabeli na stronie albo ``None`` (strona bez tabeli PKO BP)."""
    for anchor in (w for w in page_words if w.key == "ssgw"):
        reach = 4 * anchor.height
        band = [
            w
            for w in page_words
            if abs(w.cy - anchor.cy) <= reach and w.x1 <= anchor.x1 + anchor.height
        ]
        hits: dict[str, list[Word]] = {}
        for col, keys in _HEADER_KEYS.items():
            found = [w for w in band if w.key in keys]
            if not found:
                break
            hits[col] = found
        else:
            centers = [median(w.cx for w in hits[col]) for col in COLUMNS]
            if centers != sorted(centers):
                continue  # słowa nagłówka nie stoją w kolejności kolumn
            header_words = [w for col in COLUMNS for w in hits[col]]
            top = min(w.top for w in header_words)
            bottom = max(w.bottom for w in header_words)
            # Pozostałe słowa nagłówka („Zaangażowania", „MD", „netto") — tylko
            # ze słownika nagłówka i tylko w liniach przylegających do niego.
            # Słowo spoza słownika to już pierwszy wiersz tabeli: przy zerowych
            # marginesach komórek linia „Inżynier" styka się z nagłówkiem.
            members: dict[str, list[Word]] = {col: list(hits[col]) for col in COLUMNS}
            taken = {id(w) for w in header_words}
            for w in sorted(band, key=lambda item: item.top):
                if id(w) in taken or w.key not in _HEADER_VOCAB:
                    continue
                if w.top < top - anchor.height or w.top > bottom + 0.8 * anchor.height:
                    continue
                nearest = min(range(len(COLUMNS)), key=lambda i: abs(centers[i] - w.cx))
                members[COLUMNS[nearest]].append(w)
                bottom = max(bottom, w.bottom)
            extents = {
                col: (min(w.x0 for w in ws), max(w.x1 for w in ws))
                for col, ws in members.items()
            }
            rate_words = sorted(members["rate"], key=lambda w: (round(w.cy), w.x0))
            rate_label = " ".join(w.text for w in rate_words)
            if "brutto" not in fold(rate_label):
                rate_label = LABELS["rate"]
            return _Header(anchor.page, top, bottom, extents, rate_label)
    return None


def _boundaries(
    extents: dict[str, tuple[float, float]], body: Sequence[Word]
) -> list[float]:
    """Granice między kolumnami: najszerszy wolny pas w odstępie nagłówków."""
    result: list[float] = []
    for left, right in zip(COLUMNS, COLUMNS[1:]):
        lo = extents[left][1]
        hi = extents[right][0]
        if hi <= lo:  # nagłówki stykają się — granica w połowie środków
            mid = (sum(extents[left]) / 2 + sum(extents[right]) / 2) / 2
            lo, hi = mid - 0.5, mid + 0.5
        covered = sorted(
            (max(w.x0, lo), min(w.x1, hi)) for w in body if w.x1 > lo and w.x0 < hi
        )
        free: list[tuple[float, float]] = []
        cursor = lo
        for start, end in covered:
            if start > cursor:
                free.append((cursor, start))
            cursor = max(cursor, end)
        if cursor < hi:
            free.append((cursor, hi))
        if free:
            start, end = max(free, key=lambda span: span[1] - span[0])
            result.append((start + end) / 2)
        else:
            result.append((lo + hi) / 2)
    return result


def _column_of(word: Word, bounds: Sequence[float]) -> int:
    for i, bound in enumerate(bounds):
        if word.cx < bound:
            return i
    return len(bounds)


# ── Linie i komórki ─────────────────────────────────────────────────────────


@dataclass
class _Line:
    words: list[Word]

    @property
    def top(self) -> float:
        return min(w.top for w in self.words)

    @property
    def bottom(self) -> float:
        return max(w.bottom for w in self.words)

    @property
    def text(self) -> str:
        return " ".join(w.text for w in sorted(self.words, key=lambda w: w.x0))


def _lines(words: Sequence[Word], tolerance: float) -> list[_Line]:
    lines: list[_Line] = []
    for word in sorted(words, key=lambda w: (w.cy, w.x0)):
        if lines and abs(lines[-1].words[-1].cy - word.cy) <= tolerance:
            lines[-1].words.append(word)
        else:
            lines.append(_Line([word]))
    return lines


#: Wyrównanie komórek w pionie, w kolejności preferencji (PKO BP: do środka).
ALIGNMENTS = ("middle", "top", "bottom")


def _assign_lines(
    lines: Sequence[_Line],
    anchors: Sequence[Word],
    height: float,
    alignment: str,
) -> tuple[list[list[_Line]], list[float], float]:
    """Linie kolumny → komórki wierszy (DP; linie i wiersze idą w tej samej kolejności).

    Koszt grupy to odległość jej środka od środka daty wiersza (komórki
    wyśrodkowane), jej góry od góry daty (do góry) albo dołu od dołu daty (do
    dołu) — wyrównanie wybiera ``read_table`` dla całej tabeli, bo przy zerowych
    marginesach mieszanie kryteriów pozwala przesunąć linię do sąsiedniego
    wiersza bez kosztu. Grupa nie może sięgać linii dat sąsiedniego wiersza.
    Linia pominięta kosztuje ``height`` (stopka strony, przypis), więc linia
    komórki zawsze woli dołączyć do swojego wiersza.
    """
    n, m = len(lines), len(anchors)
    skip = height
    gap_limit = 1.5 * height
    inf = float("inf")
    best = [[inf] * (m + 1) for _ in range(n + 1)]
    back: list[list[Optional[tuple]]] = [[None] * (m + 1) for _ in range(n + 1)]
    best[0][0] = 0.0

    def cost(i: int, j: int, k: int) -> float:
        group = lines[i:j]
        top, bottom = group[0].top, group[-1].bottom
        # Komórka nie sięga linii dat sąsiedniego wiersza — leży w paśmie
        # swojego wiersza bez względu na wyrównanie.
        if k > 0 and top <= anchors[k - 1].cy:
            return inf
        if k + 1 < m and bottom >= anchors[k + 1].cy:
            return inf
        anchor = anchors[k]
        if alignment == "top":
            return abs(top - anchor.top)
        if alignment == "bottom":
            return abs(bottom - anchor.bottom)
        return abs((top + bottom) / 2 - anchor.cy)

    for i in range(n + 1):
        for k in range(m + 1):
            here = best[i][k]
            if here == inf:
                continue
            if i < n and here + skip < best[i + 1][k]:
                best[i + 1][k] = here + skip
                back[i + 1][k] = ("skip_line", i, k)
            if k < m:
                if here < best[i][k + 1]:
                    best[i][k + 1] = here
                    back[i][k + 1] = ("empty", i, k)
                if k > 0 and i < n and lines[i].top <= anchors[k - 1].cy:
                    continue  # grupa zaczynałaby się w poprzednim wierszu
                for j in range(i + 1, n + 1):
                    if j - 1 > i and lines[j - 1].top - lines[j - 2].bottom > gap_limit:
                        break  # komórka nie ma dziur wyższych niż linia
                    if k + 1 < m and lines[j - 1].bottom >= anchors[k + 1].cy:
                        break  # dłuższa grupa sięgnęłaby następnego wiersza
                    total = here + cost(i, j, k)
                    if total == inf:
                        continue
                    if total < best[j][k + 1]:
                        best[j][k + 1] = total
                        back[j][k + 1] = ("group", i, k)
    cells: list[list[_Line]] = [[] for _ in range(m)]
    costs = [0.0] * m
    i, k = n, m
    while (i, k) != (0, 0):
        step = back[i][k]
        if step is None:  # pragma: no cover — DP zawsze dochodzi do (0, 0)
            break
        kind, pi, pk = step
        if kind == "group":
            cells[pk] = list(lines[pi:i])
            costs[pk] = cost(pi, i, pk)
        i, k = pi, pk
    return cells, costs, best[n][m]


def _join_name(lines: Sequence[_Line]) -> str:
    """Nazwisko z kilku linii; przeniesienie („Nowak-" / „Kowalska") bez spacji."""
    text = ""
    for line in lines:
        part = line.text
        if not text:
            text = part
        elif text.endswith("-") or part.startswith("-") or part[:1].islower():
            text += part
        else:
            text += " " + part
    return clean_person_name(text)


def _join(lines: Sequence[_Line]) -> str:
    return " ".join(line.text for line in lines).strip()


# ── Tabela ──────────────────────────────────────────────────────────────────


def _table_bottom(page_words: Sequence[Word], below: float) -> float:
    candidates = [
        w.top
        for w in page_words
        if w.top > below
        and (
            w.key in _END_WORDS
            or (w.text.startswith("*") and not _DIGIT_RE.search(w.text))
        )
    ]
    return min(candidates, default=float("inf"))


def read_table(words: Sequence[Word]) -> Optional[LayoutTable]:
    """Wiersze tabeli Wykonawców albo ``None``, gdy tabeli nie da się odczytać."""
    by_page: dict[int, list[Word]] = {}
    for word in words:
        by_page.setdefault(word.page, []).append(word)
    rows: list[LayoutRow] = []
    carried: Optional[tuple[_Header, list[float]]] = None
    first_header: Optional[_Header] = None
    for page in sorted(by_page):
        page_words = by_page[page]
        header = _find_header(page_words)
        if header is not None:
            first_header = first_header or header
            start_y = header.bottom
        elif carried is not None:
            header = carried[0]
            start_y = 0.0  # tabela ciągnie się z poprzedniej strony
        else:
            continue
        end_y = _table_bottom(page_words, start_y)
        body = [w for w in page_words if w.top > start_y and w.bottom <= end_y]
        if not body:
            carried = None if end_y != float("inf") else carried
            continue
        height = median(w.height for w in body)
        start_center = sum(header.extents["start"]) / 2
        end_center = sum(header.extents["end"]) / 2
        anchors = sorted(
            (
                w
                for w in body
                if _ISO_DATE_RE.match(w.text)
                and abs(w.cx - start_center) < abs(w.cx - end_center)
            ),
            key=lambda w: w.cy,
        )
        if not anchors:
            carried = None if end_y != float("inf") else carried
            continue
        span_bottom = anchors[-1].bottom + 6 * height
        table_body = [w for w in body if w.top <= span_bottom]
        bounds = (
            _boundaries(header.extents, table_body)
            if header.page == page
            else carried[1]  # type: ignore[index]
        )
        per_column: dict[str, list[Word]] = {col: [] for col in COLUMNS}
        for word in table_body:
            per_column[COLUMNS[_column_of(word, bounds)]].append(word)
        page_rows = [LayoutRow() for _ in anchors]
        lines = {
            col: _lines(per_column[col], tolerance=0.4 * height) for col in COLUMNS
        }
        options = [
            {col: _assign_lines(lines[col], anchors, height, mode) for col in COLUMNS}
            for mode in ALIGNMENTS
        ]
        # Remis rozstrzyga kolejność ``ALIGNMENTS`` (``min`` bierze pierwszy).
        chosen = min(options, key=lambda opt: sum(item[2] for item in opt.values()))
        for col in COLUMNS:
            cells, costs, _total = chosen[col]
            for row, cell, cell_cost in zip(page_rows, cells, costs):
                row.cells[col] = _join_name(cell) if col == "name" else _join(cell)
                if col == "name" and cell and cell_cost > 0.75 * height:
                    row.reasons.append(REASON_NAME_CELL)
        # Sama data w kolumnie „Początek" bez nazwiska, końca, MD i stawki to
        # nie wiersz osoby (np. data w nagłówku strony nad ciągiem tabeli).
        rows.extend(
            row
            for row in page_rows
            if any(row.cells.get(col) for col in ("name", "end", "md", "rate"))
        )
        carried = (header, bounds) if end_y == float("inf") else None
    if first_header is None or not rows:
        return None
    for row in rows:
        _check_row(row)
    return LayoutTable(rows, first_header.rate_label)


def _check_row(row: LayoutRow) -> None:
    name = row.cells.get("name", "")
    if not 2 <= len(name.split()) <= 4 or _DIGIT_RE.search(name):
        row.reasons.append(REASON_NAME)
    if not (
        _ISO_DATE_RE.match(row.cells.get("start", ""))
        and _ISO_DATE_RE.match(row.cells.get("end", ""))
    ):
        row.reasons.append(REASON_DATES)
    if not row.cells.get("md") or not row.cells.get("rate"):
        row.reasons.append(REASON_NUMBERS)
    # Kolejność i bez powtórzeń — wiersz bywa niepewny z kilku powodów.
    row.reasons = list(dict.fromkeys(row.reasons))


# ── Tekst dla modelu i reguły ───────────────────────────────────────────────


def _clean_cell(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").replace("|", "/")).strip()


def render_table(table: LayoutTable) -> str:
    """Tabela jako linie „Wykonawca N | Etykieta: wartość | …"."""
    out = [TABLE_TITLE]
    for number, row in enumerate(table.rows, start=1):
        parts = [f"{ROW_PREFIX} {number}"]
        for col in COLUMNS:
            label = table.rate_label if col == "rate" else LABELS[col]
            parts.append(f"{label}: {_clean_cell(row.cells.get(col, ''))}")
        if row.reasons:
            parts.append("Uwaga: " + _clean_cell("; ".join(row.reasons)))
        out.append(" | ".join(parts))
    return "\n".join(out)
