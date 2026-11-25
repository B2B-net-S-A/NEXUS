"""Podział tekstu aktu na jednostki redakcyjne (art., §, ust., pkt, lit.).

Czyste funkcje, bez sieci i bazy. Trzy wejścia sprowadzane do jednego formatu
linii, który czyta ``parse_lines``:

* **ELI HTML** (``api.sejm.gov.pl/eli/acts/<tj>/text.html``) — teksty jednolite
  ogłoszone od ok. 2019 r. Etykieta jednostki stoi w ``<h3>`` („Art. 61.”,
  „§ 1.”, „1.”, „1)”, „a)”), treść w ``div[data-template=xText]``. Brany jest
  tylko załącznik obwieszczenia (sam tekst jednolity); cytaty przepisów
  nieobjętych tekstem (``pro-cite-text``) i przypisy (``gloss-link``) odpadają.
* **ELI PDF** — nowsze teksty jednolite KC, KP, PIT i in. mają tylko PDF
  (pomiar 25.11.2026: 8 z 13 aktów). Linie z ``pdfplumber`` z rozmiarem
  czcionki: treść ma 10 pt, przypisy 9 pt, indeks górny 6,5 pt i wychodzi jako
  ``[1]`` („Art. 442[1].”). Odpadają stopki stron, data wydruku i obwieszczenie.
* **EUR-Lex XHTML** z CELLAR (wersja skonsolidowana) — „Artykuł 6” z tytułem,
  ustępy „1.”, punkty „a)”; znaczniki zmian „▼M1”, „►C1 … ◄” odpadają.

Numer z indeksem górnym zapisujemy jak w Dzienniku Ustaw: „442¹”, klucz
porównania ``442^1`` (``ref_key``). Cytat „art. 442^1”, „art. 442[1]”
i „art. 442¹” daje ten sam klucz.
"""

from __future__ import annotations

import html as html_lib
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from typing import Iterable, Optional, Sequence

KIND_ART = "art"
KIND_PAR = "par"
KIND_UST = "ust"
KIND_PKT = "pkt"
KIND_LIT = "lit"
KINDS: tuple[str, ...] = (KIND_ART, KIND_PAR, KIND_UST, KIND_PKT, KIND_LIT)

#: Linia nagłówka (księga, tytuł, dział, rozdział) w formacie ``parse_lines``.
HEADING_MARK = "\x00H "
#: Tytuł artykułu w aktach UE („Zgodność przetwarzania z prawem”).
TITLE_MARK = "\x00T "

_SUPERSCRIPT = str.maketrans("0123456789a", "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃ")
_FROM_SUPERSCRIPT = {ch: plain for plain, ch in zip("0123456789a", "⁰¹²³⁴⁵⁶⁷⁸⁹ᵃ")}

_NUM = r"\d+[a-z]{0,4}(?:\[[0-9a-z]{1,4}\])?"
_ART = re.compile(rf"^Art\.\s*(?P<num>{_NUM})\.\s*(?P<rest>.*)$")
_PAR = re.compile(rf"^§\s*(?P<num>{_NUM})\.\s*(?P<rest>.*)$")
_UST = re.compile(rf"^(?P<num>{_NUM})\.(?:\s+(?P<rest>.*))?$")
_PKT = re.compile(rf"^(?P<num>{_NUM})\)\s*(?P<rest>.*)$")
_LIT = re.compile(r"^(?P<num>[a-z]{1,2}(?:\[[0-9a-z]{1,4}\])?)\)\s*(?P<rest>.*)$")
_HEADING = re.compile(
    r"^(KSIĘGA|CZĘŚĆ|TYTUŁ|DZIAŁ|ROZDZIAŁ|Rozdział|ODDZIAŁ|Oddział|SEKCJA|Sekcja)\b"
)
_STOP = re.compile(r"^(ZAŁĄCZNIK|Załącznik)(\s+(nr|I|II|III|IV|V|do)\b.*)?\s*$")
_REPEALED = re.compile(r"^\((uchylony|uchylona|uchylone|skreślony|skreślona)\)\.?$")


# ── numery i klucze ─────────────────────────────────────────────────────────


def display_number(raw: str) -> str:
    """„442[1]” i „442^1” → „442¹” (jak w Dzienniku Ustaw)."""

    def _sup(match: re.Match[str]) -> str:
        inner = match.group(1)
        if all(ch in "0123456789a" for ch in inner):
            return inner.translate(_SUPERSCRIPT)
        return "^" + inner

    text = re.sub(r"\[([0-9a-z]+)\]", _sup, raw.strip())
    return re.sub(r"\^([0-9a-z]+)", _sup, text)


def key_number(raw: str) -> str:
    """Numer do klucza: „442¹”, „442[1]”, „442^1” → „442^1”; małe litery."""
    text = raw.strip().lower().replace(" ", "")
    text = re.sub(r"\[([0-9a-z]+)\]", r"^\1", text)
    out: list[str] = []
    in_sup = False
    for ch in text:
        plain = _FROM_SUPERSCRIPT.get(ch)
        if plain is not None:
            if not in_sup:
                out.append("^")
                in_sup = True
            out.append(plain)
        else:
            in_sup = False
            out.append(ch)
    return "".join(out)


_KEY_LABEL = {KIND_PAR: "§", KIND_UST: "ust.", KIND_PKT: "pkt", KIND_LIT: "lit."}


def make_key(article: str, parts: Sequence[tuple[str, str]] = ()) -> str:
    """Klucz jednostki: ``61``, ``61 §1``, ``6 ust.1 lit.b``, ``442^1 §1 pkt2``."""
    pieces = [key_number(article)]
    for kind, number in parts:
        pieces.append(f"{_KEY_LABEL[kind]}{key_number(number)}")
    return " ".join(pieces)


def make_ref(article: str, parts: Sequence[tuple[str, str]] = ()) -> str:
    """Oznaczenie do wyświetlenia: „art. 61 § 1”, „art. 6 ust. 1 lit. b”."""
    pieces = [f"art. {display_number(article)}"]
    for kind, number in parts:
        label = _KEY_LABEL[kind]
        pieces.append(f"{label} {display_number(number)}")
    return " ".join(pieces)


def _split_number(raw: str) -> tuple[int, str]:
    match = re.match(r"(\d+)(.*)", key_number(raw))
    if not match:
        return -1, raw
    return int(match.group(1)), match.group(2)


def _follows(previous: Optional[str], number: str, *, letters: bool = False) -> bool:
    """Czy ``number`` może być następną jednostką po ``previous``.

    Chroni przed linią zawiniętą w środku zdania, która zaczyna się od „2.”
    albo „3)”. Dopuszcza wstawki („1a” po „1”, „2¹” po „2”) i pierwszą
    jednostkę („1”, „a”).
    """
    if letters:
        current = key_number(number).split("^")[0]
        if previous is None:
            return current == "a"
        before = key_number(previous).split("^")[0]
        if current == before:
            return "^" in key_number(number)
        if len(current) == 1 and len(before) == 1:
            return ord(current) == ord(before) + 1
        return current.startswith(before) or len(current) > len(before)
    base, suffix = _split_number(number)
    if base < 0:
        return False
    if previous is None:
        return base == 1 or (base == 0 and bool(suffix))
    prev_base, prev_suffix = _split_number(previous)
    if base == prev_base + 1:
        return not suffix or suffix.startswith("^") or suffix == "a"
    if base == prev_base:
        return bool(suffix) and suffix != prev_suffix
    return False


# ── drzewo jednostek ────────────────────────────────────────────────────────


@dataclass
class _Node:
    kind: str
    number: str
    label: str
    parent: Optional["_Node"]
    heading: Optional[str] = None
    text_parts: list[str] = field(default_factory=list)
    children: list["_Node"] = field(default_factory=list)

    def add_text(self, line: str) -> None:
        if not line:
            return
        if self.text_parts:
            last = self.text_parts[-1]
            if (
                last.endswith("-")
                and len(last) > 1
                and last[-2].isalpha()
                and line[:1].islower()
            ):
                self.text_parts[-1] = last[:-1] + line
                return
        self.text_parts.append(line)

    def own_text(self) -> str:
        joined = " ".join(self.text_parts)
        return re.sub(r"\s+", " ", joined).strip()

    def last_child(self, kind: str) -> Optional["_Node"]:
        for child in reversed(self.children):
            if child.kind == kind:
                return child
        return None


@dataclass(frozen=True)
class ParsedUnit:
    """Jednostka redakcyjna z tekstem całego poddrzewa (z etykietami dzieci)."""

    ref: str
    key: str
    article: str
    kind: str
    depth: int
    parent_key: Optional[str]
    position: int
    text: str
    heading: Optional[str]
    repealed: bool


def _path(node: _Node) -> tuple[str, list[tuple[str, str]]]:
    chain: list[_Node] = []
    current: Optional[_Node] = node
    while current is not None:
        chain.append(current)
        current = current.parent
    chain.reverse()
    article = chain[0].number
    return article, [(n.kind, n.number) for n in chain[1:]]


def _article_of(node: _Node) -> _Node:
    while node.parent is not None:
        node = node.parent
    return node


def _subtree_text(node: _Node) -> str:
    lines = []
    own = node.own_text()
    if node.kind == KIND_ART:
        lines.append(f"Art. {display_number(node.number)}. {own}".rstrip())
    else:
        lines.append(f"{node.label} {own}".rstrip())
    for child in node.children:
        lines.append(_subtree_text(child))
    return "\n".join(line for line in lines if line)


def _flatten(articles: Sequence[_Node]) -> list[ParsedUnit]:
    units: list[ParsedUnit] = []
    seen: set[str] = set()

    def visit(node: _Node, depth: int, parent_key: Optional[str]) -> None:
        article, parts = _path(node)
        key = make_key(article, parts)
        if key in seen:
            # Powtórzony numer to błąd odczytu (np. przypis z „1)”), nie nowa
            # jednostka — pierwsza wygrywa, dzieci powtórki też odpadają.
            return
        seen.add(key)
        own = node.own_text()
        units.append(
            ParsedUnit(
                ref=make_ref(article, parts),
                key=key,
                article=display_number(article),
                kind=node.kind,
                depth=depth,
                parent_key=parent_key,
                position=len(units),
                text=_subtree_text(node),
                heading=node.heading or _article_of(node).heading,
                repealed=bool(_REPEALED.match(own)) and not node.children,
            )
        )
        for child in node.children:
            visit(child, depth + 1, key)

    for article in articles:
        visit(article, 0, None)
    return units


class _Builder:
    def __init__(self) -> None:
        self.articles: list[_Node] = []
        self.heading: Optional[str] = None
        self._heading_open = False
        self.article: Optional[_Node] = None
        self.section: Optional[_Node] = None  # § albo ust.
        self.point: Optional[_Node] = None
        self.letter: Optional[_Node] = None

    def deepest(self) -> Optional[_Node]:
        return self.letter or self.point or self.section or self.article

    def heading_line(self, text: str) -> None:
        text = text.strip()
        if not text:
            return
        if self._heading_open and self.heading:
            self.heading = f"{self.heading} — {text}"[:300]
        else:
            self.heading = text[:300]
        self._heading_open = True

    def start_article(self, number: str, rest: str) -> None:
        self._heading_open = False
        node = _Node(KIND_ART, number, f"Art. {number}.", None, heading=self.heading)
        self.articles.append(node)
        self.article, self.section, self.point, self.letter = node, None, None, None
        self.content(rest, fresh=True)

    def start_section(self, kind: str, number: str, rest: str) -> None:
        assert self.article is not None
        label = (
            f"§ {display_number(number)}."
            if kind == KIND_PAR
            else (f"{display_number(number)}.")
        )
        node = _Node(kind, number, label, self.article)
        self.article.children.append(node)
        self.section, self.point, self.letter = node, None, None
        self.content(rest, fresh=True)

    def start_point(self, number: str, rest: str) -> None:
        parent = self.section or self.article
        assert parent is not None
        node = _Node(KIND_PKT, number, f"{display_number(number)})", parent)
        parent.children.append(node)
        self.point, self.letter = node, None
        self.content(rest, fresh=True)

    def start_letter(self, number: str, rest: str) -> None:
        parent = self.point or self.section or self.article
        assert parent is not None
        node = _Node(KIND_LIT, number, f"{display_number(number)})", parent)
        parent.children.append(node)
        self.letter = node
        self.content(rest, fresh=True)

    def content(self, line: str, *, fresh: bool = False) -> None:
        line = line.strip()
        if not line:
            return
        if self.article is None:
            return
        if self._try_units(line, allow_section=True):
            return
        target = self.deepest()
        if target is not None:
            target.add_text(line)

    def _try_units(self, line: str, *, allow_section: bool) -> bool:
        article = self.article
        if article is None:
            return False
        match = _PAR.match(line)
        if match and allow_section:
            previous = article.last_child(KIND_PAR)
            if not article.children or previous is not None:
                if _follows(previous.number if previous else None, match["num"]):
                    self.start_section(KIND_PAR, match["num"], match["rest"] or "")
                    return True
        match = _UST.match(line)
        if match and allow_section and article.last_child(KIND_PAR) is None:
            previous = article.last_child(KIND_UST)
            # Ustęp wchodzi tylko na poziom artykułu: pierwszy „1.”, gdy artykuł
            # nie ma jeszcze punktów, kolejne po poprzednim ustępie.
            if (previous is not None or not article.children) and _follows(
                previous.number if previous else None, match["num"]
            ):
                self.start_section(KIND_UST, match["num"], match["rest"] or "")
                return True
        match = _PKT.match(line)
        if match:
            parent = self.section or article
            previous = parent.last_child(KIND_PKT)
            if _follows(previous.number if previous else None, match["num"]):
                self.start_point(match["num"], match["rest"] or "")
                return True
        match = _LIT.match(line)
        if match:
            parent = self.point or self.section or article
            previous = parent.last_child(KIND_LIT)
            if _follows(
                previous.number if previous else None, match["num"], letters=True
            ):
                self.start_letter(match["num"], match["rest"] or "")
                return True
        return False


def parse_lines(lines: Iterable[str]) -> list[ParsedUnit]:
    """Jednostki redakcyjne z linii tekstu aktu (od pierwszego „Art.”).

    Linia z ``HEADING_MARK`` to nagłówek (rozdział i jego nazwa), z
    ``TITLE_MARK`` — tytuł artykułu w akcie UE. Linia ``Załącznik`` kończy
    tekst ustawy (załączniki to tabele, nie jednostki redakcyjne).
    """
    builder = _Builder()
    for raw in lines:
        if raw.startswith(HEADING_MARK):
            builder.heading_line(raw[len(HEADING_MARK) :])
            continue
        if raw.startswith(TITLE_MARK):
            if builder.article is not None and not builder.article.children:
                title = raw[len(TITLE_MARK) :].strip()
                builder.article.heading = (
                    f"{builder.heading} — {title}" if builder.heading else title
                )[:300]
            continue
        line = raw.strip()
        if not line:
            continue
        if builder.articles and _STOP.match(line):
            break
        match = _ART.match(line)
        if match:
            builder.start_article(match["num"], match["rest"] or "")
            continue
        if builder._heading_open:
            builder.heading_line(line)
            continue
        if builder.article is None:
            continue
        builder.content(line)
    return _flatten(builder.articles)


# ── PDF (ELI) ───────────────────────────────────────────────────────────────

_PAGE_NOISE = (
    re.compile(r"^©\s*Kancelaria Sejmu\b.*$"),
    re.compile(r"^Dziennik Ustaw\s+–\s*\d+\s*–\s*Poz\.\s*\d+\s*$"),
    re.compile(r"^\d{4}-\d{2}-\d{2}$"),
)


@dataclass(frozen=True)
class PdfLine:
    text: str
    size: float


def pdf_body_lines(lines: Sequence[PdfLine]) -> list[str]:
    """Linie treści aktu z PDF-u tekstu jednolitego.

    * pomija obwieszczenie (do linii „Załącznik do obwieszczenia …”, jeśli jest),
    * pomija przypisy (czcionka wyraźnie mniejsza niż treść) i stopki stron,
    * nagłówki („TYTUŁ VI”, „Rozdział 2”) oznacza ``HEADING_MARK``.
    """
    if not lines:
        return []
    sizes = sorted(round(line.size, 1) for line in lines if line.text.strip())
    body_size = sizes[len(sizes) // 2] if sizes else 10.0
    start = 0
    for index, line in enumerate(lines):
        if line.text.strip().startswith("Załącznik do obwieszczenia"):
            start = index + 1
            break
    out: list[str] = []
    for line in lines[start:]:
        text = line.text.strip()
        if not text or any(p.match(text) for p in _PAGE_NOISE):
            continue
        if line.size < body_size - 0.6:
            continue
        if _HEADING.match(text) and len(text) <= 80:
            out.append(HEADING_MARK + text)
            continue
        out.append(text)
    return out


def read_pdf_lines(path: str) -> list[PdfLine]:
    """Linie PDF-u z rozmiarem czcionki (blokujące — wołać w wątku)."""
    from collections import Counter

    import pdfplumber  # type: ignore[import-untyped]

    result: list[PdfLine] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            for line in page.extract_text_lines(return_chars=True):
                chars = line.get("chars") or []
                if chars:
                    size = Counter(round(c["size"], 1) for c in chars).most_common(1)[
                        0
                    ][0]
                else:
                    size = 0.0
                result.append(PdfLine(line.get("text") or "", float(size)))
            page.flush_cache()
    return result


# ── HTML (ELI) ──────────────────────────────────────────────────────────────

_UNIT_KINDS = {"arti", "para", "pass", "pint", "lett"}
_STRUCT_KINDS = {"book", "part", "titl", "bran", "chpt", "sect", "subs", "divi"}


class _EliHtml(HTMLParser):
    """ELI HTML → linie ``parse_lines`` (etykieta + treść jednostki)."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.lines: list[str] = []
        self._stack: list[tuple[str, str]] = []  # (tag, rola)
        self._skip = 0
        self._label: Optional[list[str]] = None
        self._text: Optional[list[str]] = None
        self._pending_label: Optional[str] = None
        self._struct_label = False
        self._sup = False
        self.in_body = False

    def _role(self, tag: str, attrs: dict[str, str]) -> str:
        cls = attrs.get("class", "") or ""
        if tag == "div" and cls.split()[:1] == ["part"]:
            return "part"
        if tag == "a" and "gloss-link" in cls:
            return "skip"
        if tag == "div" and cls.startswith("unit "):
            if "pro-cite" in cls:
                return "skip"
            kind = next((c[5:] for c in cls.split() if c.startswith("unit_")), "")
            if kind in _UNIT_KINDS:
                return "unit"
            if kind in _STRUCT_KINDS:
                return "struct"
            if kind == "tire":
                return "tiret"
            return "other"
        if tag == "div" and attrs.get("data-template") == "xText":
            return "text"
        if (
            tag in ("h3", "h2")
            and self._stack
            and self._stack[-1][1]
            in (
                "unit",
                "struct",
                "tiret",
            )
        ):
            return "label"
        if tag == "sup":
            return "sup"
        return ""

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        if tag in ("br", "img", "hr", "meta", "link", "col", "input"):
            return
        attrs = {k: (v or "") for k, v in attrs_list}
        role = self._role(tag, attrs)
        self._stack.append((tag, role))
        if self._skip:
            if role == "skip" or tag:
                self._skip += 1
            return
        if role == "skip":
            self._skip = 1
            return
        if role == "part":
            # Tylko część z tekstem jednolitym (załącznik obwieszczenia).
            self.in_body = False
        if role == "label":
            if self._pending_label and self.in_body:
                # Artykuł bez własnej treści („Art. 2.”, a pod nim od razu ust. 1).
                self.lines.append(self._pending_label)
            self._pending_label = None
            self._label = []
            parent_role = self._stack[-2][1] if len(self._stack) > 1 else ""
            self._struct_label = parent_role == "struct"
        elif role == "text":
            self._text = []
        elif role == "sup":
            self._sup = True
            if self._label is not None:
                self._label.append("[")
            elif self._text is not None:
                self._text.append("[")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("br", "img", "hr", "meta", "link", "col", "input"):
            return
        if not self._stack:
            return
        _tag, role = self._stack.pop()
        if self._skip:
            self._skip -= 1
            return
        if role == "sup":
            self._sup = False
            if self._label is not None:
                self._label.append("]")
            elif self._text is not None:
                self._text.append("]")
        elif role == "label" and self._label is not None:
            label = _clean("".join(self._label))
            self._label = None
            if not self.in_body:
                return
            if self._struct_label:
                self.lines.append(HEADING_MARK + label)
            else:
                self._pending_label = label
        elif role == "text" and self._text is not None:
            text = _clean("".join(self._text))
            self._text = None
            if not self.in_body or not text:
                return
            if self._pending_label:
                self.lines.append(f"{self._pending_label} {text}")
                self._pending_label = None
            else:
                self.lines.append(text)
        elif role in ("unit", "tiret") and self._pending_label:
            if self.in_body:
                self.lines.append(self._pending_label)
            self._pending_label = None

    def handle_data(self, data: str) -> None:
        if self._skip:
            return
        if self._label is not None:
            self._label.append(data)
        elif self._text is not None:
            self._text.append(data)
        elif (
            "Załącznik" in data
            and any(tag == "h2" for tag, _role in self._stack)
            and any(role == "part" for _t, role in self._stack)
        ):
            self.in_body = True


def _clean(text: str) -> str:
    text = html_lib.unescape(text).replace("\xa0", " ")
    text = re.sub(r"\[\s*", "[", text)
    text = re.sub(r"\s*\]", "]", text)
    return re.sub(r"\s+", " ", text).strip()


def eli_html_lines(document: str) -> list[str]:
    """Linie ``parse_lines`` z ELI HTML tekstu jednolitego.

    Dokument bez części „Załącznik” (akt ogłoszony bez obwieszczenia) czytamy
    w całości.
    """
    parser = _EliHtml()
    if "Załącznik" not in document:
        parser.in_body = True
    parser.feed(document)
    parser.close()
    return parser.lines


# ── XHTML (EUR-Lex / CELLAR) ────────────────────────────────────────────────

_EU_ARTICLE = re.compile(r"^Artykuł\s+(\d+[a-z]{0,3})\s*$")
_EU_HEADING = re.compile(
    r"^(ROZDZIAŁ|SEKCJA|TYTUŁ|CZĘŚĆ|Rozdział|Sekcja)\s+[0-9IVXLC]+"
)
_EU_MARKERS = re.compile(r"[▼►◄]\s*[A-Z]?\d*")
_EU_BLOCK_TAGS = {"p", "div", "td", "li", "h1", "h2", "h3", "h4", "tr"}


class _EurLexText(HTMLParser):
    """XHTML EUR-Lex → płaskie linie tekstu z klasą akapitu."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[tuple[str, str]] = []
        self._buffer: list[str] = []
        self._classes: list[str] = []
        self._skip = 0

    def _flush(self) -> None:
        text = _clean("".join(self._buffer))
        self._buffer = []
        if text:
            cls = next((c for c in reversed(self._classes) if c), "")
            self.blocks.append((cls, text))

    def handle_starttag(self, tag: str, attrs_list: list) -> None:
        attrs = {k: (v or "") for k, v in attrs_list}
        if tag in ("script", "style", "head"):
            self._skip += 1
            return
        if tag in _EU_BLOCK_TAGS:
            self._flush()
        if tag in _EU_BLOCK_TAGS:
            self._classes.append(attrs.get("class", ""))
        if tag == "span" and "no-parag" in attrs.get("class", ""):
            self._flush()

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style", "head"):
            self._skip = max(0, self._skip - 1)
            return
        if tag in _EU_BLOCK_TAGS:
            # Etykieta listy („a) ”) stoi w osobnej komórce siatki — dokleja się
            # do następnego akapitu zamiast tworzyć własną linię.
            if self._buffer and re.fullmatch(
                r"\s*(\(?[a-z0-9]{1,4}\)|\d+\.)\s*", "".join(self._buffer)
            ):
                if self._classes:
                    self._classes.pop()
                return
            self._flush()
            if self._classes:
                self._classes.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self._buffer.append(data)


def eurlex_lines(document: str) -> list[str]:
    """Linie ``parse_lines`` z XHTML wersji skonsolidowanej aktu UE.

    Motywy (preambuła) odpadają, bo ``parse_lines`` zaczyna od pierwszego
    artykułu; załączniki kończą tekst.
    """
    parser = _EurLexText()
    parser.feed(document)
    parser.close()
    parser._flush()
    out: list[str] = []
    expect_title = False
    for cls, raw in parser.blocks:
        if "footnote" in cls:
            continue
        text = _EU_MARKERS.sub("", raw).strip()
        # Odsyłacz do przypisu: „( 1 )” ze spacjami (zwykłe „(1)” w tekście ich nie ma).
        text = re.sub(r"\s*\(\s+\d+\s+\)", "", text)
        text = re.sub(r"\s+", " ", text)
        if not text:
            continue
        match = _EU_ARTICLE.match(text)
        if match:
            out.append(f"Art. {match.group(1)}.")
            expect_title = True
            continue
        if expect_title and ("stitle" in cls or "sti-art" in cls):
            out.append(TITLE_MARK + text)
            expect_title = False
            continue
        expect_title = False
        if _EU_HEADING.match(text) or cls in ("title-division-1", "ti-section-1"):
            out.append(HEADING_MARK + text)
            continue
        if cls.startswith("title-division-2") or cls.startswith("ti-section-2"):
            out.append(HEADING_MARK + text)
            continue
        if re.match(r"^ZAŁĄCZNIK\b", text):
            out.append("ZAŁĄCZNIK")
            continue
        out.append(text)
    return out
