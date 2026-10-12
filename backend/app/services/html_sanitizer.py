"""Allowlist sanitizer HTML dla materiałów CV (M4 audyt P1.9, PR-04).

Branded HTML pochodzi z edytowalnej treści (AI + ręczne poprawki rekrutera,
tekst z CV kandydata). Publiczna karta i authenticated printable flow
renderują go w przeglądarce — bez sanityzacji to stored-active-content risk
(XSS w publicznym linku wysyłanym klientowi).

Polityka: allowlist (bleach), NIE blocklist:
- tagi prezentacyjne + struktura dokumentu; zero script/iframe/object/embed/
  form/input,
- atrybuty: style/class + href/src/alt/title/col-rowspan; zero on* handlerów
  (bleach wycina wszystko spoza listy),
- protokoły: https/mailto/tel + data: (inline logo w img); javascript: jest
  poza listą → wycięte,
- CSS w ``style=`` filtrowany przez CSSSanitizer (position:fixed itp. nie ma
  potrzeby blokować — brak skryptów; tniemy tylko do bezpiecznych własności
  prezentacyjnych) i bez wartości ładujących zasób (url(), image-set()) —
  inaczej CV otwarte przez klienta wysyła żądanie na adres wpisany w treść.
  Arkusz szablonu dokłada ``cv_public_document`` z kodu, nie z treści.

Sanityzujemy NA WYJŚCIU (public share + printable), nie w storage — treść
źródłowa zostaje nienaruszona dla edytora, a polityka może się zaostrzać bez
migracji danych.
"""

from __future__ import annotations

import re
from html import escape as html_escape
from html.parser import HTMLParser

import tinycss2
from bleach import html5lib_shim
from bleach.css_sanitizer import CSSSanitizer
from bleach.sanitizer import Cleaner

ALLOWED_TAGS = [
    "a",
    "abbr",
    "article",
    "aside",
    "b",
    "blockquote",
    "br",
    "caption",
    "code",
    "div",
    "em",
    "footer",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "header",
    "hr",
    "i",
    "img",
    "li",
    "main",
    "mark",
    "ol",
    "p",
    "pre",
    "s",
    "section",
    "small",
    "span",
    "strong",
    "sub",
    "sup",
    "table",
    "tbody",
    "td",
    "tfoot",
    "th",
    "thead",
    "tr",
    "u",
    "ul",
]

ALLOWED_ATTRIBUTES = {
    "*": ["style", "class"],
    "p": ["data-cv-section"],
    "h2": ["data-cv-section"],
    "a": ["href", "title", "rel"],
    "img": ["src", "alt", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan", "scope"],
    "abbr": ["title"],
}

# data: potrzebne dla inline logo/zdjęcia w brandowanym CV. javascript: i
# file: są poza listą → bleach usuwa cały atrybut.
ALLOWED_PROTOCOLS = ["https", "http", "mailto", "tel", "data"]

# Funkcje CSS, którymi przeglądarka pobiera zasób z sieci.
_FETCHING_FUNCTIONS = {
    "url",
    "src",
    "image",
    "image-set",
    "-webkit-image-set",
    "cross-fade",
    "element",
}


def _fetches(tokens) -> bool:
    for token in tokens:
        if token.type == "url":
            return True
        if token.type == "function" and (
            token.lower_name in _FETCHING_FUNCTIONS or _fetches(token.arguments)
        ):
            return True
        if token.type in ("() block", "[] block", "{} block") and _fetches(
            token.content
        ):
            return True
    return False


class _NoFetchCSSSanitizer(CSSSanitizer):
    """Allowlista własności + odrzucenie deklaracji, które pobierają zasób.

    Bleach sprawdza tylko nazwę własności, więc ``background:url(https://…)``
    przechodził w całości.
    """

    def sanitize_css(self, style):
        # Token błędu (urwane ``font-size``, zbłąkany nawias) nie daje się
        # zserializować — do 12.10.2026 kończył zapis CV wyjątkiem. Zła
        # deklaracja znika, reszta stylu zostaje.
        try:
            kept = [
                token
                for token in tinycss2.parse_declaration_list(style)
                if token.type != "error"
                and not (token.type == "declaration" and _fetches(token.value))
            ]
            return super().sanitize_css(tinycss2.serialize(kept))
        except RecursionError:
            # Kilkaset zagnieżdżonych nawiasów w wartości (``f(f(f(…``) — styl
            # znika w całości, zapis CV nie kończy się błędem 500.
            return ""


_CSS_SANITIZER = _NoFetchCSSSanitizer(
    allowed_css_properties=[
        "background",
        "background-color",
        "border",
        "border-bottom",
        "border-collapse",
        "border-color",
        "border-left",
        "border-radius",
        "border-right",
        "border-top",
        "color",
        "display",
        "float",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-weight",
        "gap",
        "height",
        "letter-spacing",
        "line-height",
        "list-style",
        "list-style-type",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "min-height",
        "min-width",
        "opacity",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "page-break-after",
        "page-break-before",
        "page-break-inside",
        "text-align",
        "text-decoration",
        "text-transform",
        "vertical-align",
        "white-space",
        "width",
        "word-break",
    ]
)


# html5lib w bleach płaci za każdy znacznik czasem proporcjonalnym do głębokości
# drzewa: 500 KB zagnieżdżonych ``<div>`` — tyle mieści pole ``content_html`` —
# trwało kilka minut w jednym żądaniu, a handlery wołają sanitizer w pętli
# zdarzeń. Głębokość liczy sam parser (``_OpenElements``), bo tylko on wie, co
# naprawdę jest otwarte: ``<li><h1>`` albo ``<b><div></b>`` powtarzane w kółko
# budują głębokie drzewo, choć w tekście nic nie wygląda na zagnieżdżone.
# CV z generatora ma 7–8 poziomów, wklejone z Worda kilkanaście.
MAX_TREE_DEPTH = 80
# Drzewo ponad limit jest składane drugi raz ze spłaszczonej treści: najwyżej
# tyle znaczników otwartych naraz, kolejne są pomijane (tekst zostaje).
MAX_NESTING = 32
# Treść wpisana wprost w ``<table>`` (poza komórką) parser przenosi przed
# tabelę, za każdym razem przeglądając rodzeństwo tabeli — tysiące takich
# elementów to znów czas kwadratowy. Ponad limit tabele są rozbierane na tekst.
MAX_MISNESTED_IN_TABLE = 1000
# Tokenizer html5lib porównuje każdy atrybut znacznika ze wszystkimi
# wcześniejszymi: 10 000 atrybutów w jednym znaczniku to kilkadziesiąt sekund.
# Znacznik z dłuższą listą trafia do parsera z pierwszymi atrybutami.
MAX_ATTRIBUTES = 64

_VOID_TAGS = frozenset(
    "area base br col embed hr img input link meta source track wbr".split()
)
_TABLE_TAGS = frozenset("table thead tbody tfoot tr td th caption colgroup col".split())
_PLAIN_ATTRIBUTE_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_:.-]*\Z")


class _TreeTooCostly(Exception):
    """Parser HTML przekroczył limit pracy — treść idzie drogą awaryjną."""


class _TreeTooDeep(_TreeTooCostly):
    """Parser otworzył więcej elementów naraz niż ``MAX_TREE_DEPTH``."""


class _TableMisnested(_TreeTooCostly):
    """Za dużo treści wpisanej wprost w tabelę (``MAX_MISNESTED_IN_TABLE``)."""


class _OpenElements(list):
    """Stos otwartych elementów html5lib, który przerywa zbyt głębokie drzewo."""

    def append(self, element):
        if len(self) >= MAX_TREE_DEPTH:
            raise _TreeTooDeep
        super().append(element)

    def insert(self, index, element):
        if len(self) >= MAX_TREE_DEPTH:
            raise _TreeTooDeep
        super().insert(index, element)


class _IndexedTreeWalker(html5lib_shim.getTreeWalker("etree")):
    """Walker html5lib, który pamięta pozycję rodzica zamiast jej szukać.

    Oryginał przy powrocie z dziecka do rodzica przegląda całe rodzeństwo
    rodzica (``list(...).count`` i ``.index``), więc tysiące akapitów
    z pogrubieniem w środku kosztowały czas kwadratowy: 33 tys. akapitów
    (500 KB) to ponad 40 s. Kolejność i treść tokenów są te same.
    """

    def __init__(self, tree):
        super().__init__(tree)
        # Pozycje elementów z ``parents``, w tej samej kolejności.
        self._keys: list = []

    def _descend(self, node, step):
        # `parents` to ta sama lista przed i po kroku — długość trzeba zmierzyć
        # przed wywołaniem oryginału.
        is_tuple = isinstance(node, tuple)
        before = len(node[2]) if is_tuple else 0
        child = step(node)
        if child is not None and len(child[2]) > before:
            self._keys.append(node[1] if is_tuple else None)
        return child

    def getFirstChild(self, node):
        return self._descend(node, super().getFirstChild)

    def getNextSibling(self, node):
        return self._descend(node, super().getNextSibling)

    def getParentNode(self, node):
        if not isinstance(node, tuple):
            return None
        element, key, parents, flag = node
        if flag == "text":
            return (element, key, parents, None) if parents else element
        parent = parents.pop()
        parent_key = self._keys.pop()
        return (parent, parent_key, parents, None) if parents else parent


def _allowlisted(markup: str) -> str:
    """``bleach.clean`` z limitem głębokości drzewa i szybkim walkerem."""
    cleaner = Cleaner(
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )
    tree = cleaner.parser.tree
    reset = tree.reset

    def guarded_reset():
        reset()
        tree.openElements = _OpenElements(tree.openElements)

    tree.reset = guarded_reset
    misnested_position = tree.getTableMisnestedNodePosition
    misnested = 0

    def counted_position():
        nonlocal misnested
        misnested += 1
        if misnested > MAX_MISNESTED_IN_TABLE:
            raise _TableMisnested
        return misnested_position()

    tree.getTableMisnestedNodePosition = counted_position
    cleaner.walker = _IndexedTreeWalker
    return cleaner.clean(markup)


class _VisibleCVMarkup(HTMLParser):
    """Remove non-visible content before allowlisting presentation markup.

    Bleach strip=True removes a style/script tag but keeps its raw code as text.
    Full-document imports must not print that code in the approved document.

    ``flatten`` (tylko dla treści, na której parser przekroczył
    ``MAX_TREE_DEPTH``) oddaje znaczniki ściśle zagnieżdżone i najwyżej
    ``MAX_NESTING`` otwartych naraz: znacznik otwarty ponad limit i zamknięcie,
    które nie pasuje do ostatnio otwartego, są pomijane. Parser nie ma wtedy
    z czego zbudować głębszego drzewa. ``plain_tables`` zamienia znaczniki tabel
    na odstępy, ``text_only`` oddaje sam tekst.
    """

    hidden_tags = {"head", "style", "script", "template", "noscript"}

    def __init__(
        self,
        *,
        flatten: bool = False,
        plain_tables: bool = False,
        text_only: bool = False,
    ):
        super().__init__(convert_charrefs=False)
        # Otwarte ukryte znaczniki: ile ich jest i pod którym numerem każdy
        # rodzaj otworzył się pierwszy raz. Lista z przeszukiwaniem przy każdym
        # znaczniku zamykającym kosztowała czas kwadratowy (50 000 ``<head>``).
        self.hidden = 0
        self.hidden_first: dict[str, int] = {}
        self.parts = []
        self.flatten = flatten
        self.plain_tables = plain_tables
        self.text_only = text_only
        # Tryb `flatten`: otwarte znaczniki (nazwa, czy trafił do wyniku).
        self.open: list[tuple[str, bool]] = []
        self.depth = 0

    def _skipped(self, tag: str) -> bool:
        if self.text_only or (self.plain_tables and tag in _TABLE_TAGS):
            # Odstęp zamiast znacznika, żeby sąsiednie słowa się nie skleiły.
            self.parts.append(" ")
            return True
        return False

    def _opened(self, tag: str) -> bool:
        if self._skipped(tag):
            return False
        if not self.flatten or tag in _VOID_TAGS:
            return True
        kept = self.depth < MAX_NESTING
        self.open.append((tag, kept))
        self.depth += kept
        return kept

    def _closed(self, tag: str) -> bool:
        if self._skipped(tag):
            return False
        if not self.flatten:
            return True
        if not self.open or self.open[-1][0] != tag:
            return False
        kept = self.open.pop()[1]
        self.depth -= kept
        return kept

    def _start_tag(self, tag: str, attrs) -> str:
        if len(attrs) <= MAX_ATTRIBUTES:
            return self.get_starttag_text()
        kept = "".join(
            f" {name}" if value is None else f' {name}="{html_escape(value)}"'
            for name, value in attrs[:MAX_ATTRIBUTES]
            if _PLAIN_ATTRIBUTE_NAME.match(name)
        )
        return f"<{tag}{kept}>"

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden_tags:
            self.hidden_first.setdefault(tag, self.hidden)
            self.hidden += 1
        elif not self.hidden and self._opened(tag):
            self.parts.append(self._start_tag(tag, attrs))

    def handle_startendtag(self, tag, attrs):
        # ``<div/>`` to dla parsera HTML zwykłe otwarcie, nie element pusty.
        if not self.hidden and tag not in self.hidden_tags and self._opened(tag):
            self.parts.append(self._start_tag(tag, attrs))

    def handle_endtag(self, tag):
        first = self.hidden_first.get(tag)
        if first is not None:
            # Zamknięcie zdejmuje ten znacznik od PIERWSZEGO otwarcia razem ze
            # wszystkim, co otworzyło się po nim.
            self.hidden = first
            self.hidden_first = {
                name: index
                for name, index in self.hidden_first.items()
                if index < first
            }
        elif not self.hidden and tag not in self.hidden_tags and self._closed(tag):
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self.hidden:
            return
        if self.flatten or self.plain_tables or self.text_only:
            # Tekst z ``<textarea>`` / ``<title>`` przychodzi tu surowy. Gdy jego
            # znacznik został pominięty, ``<div>`` w tym tekście stałby się
            # prawdziwym znacznikiem — poza limitem zagnieżdżenia.
            data = data.replace("<", "&lt;")
        self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def _visible(html: str, **mode: bool) -> str:
    markup = _VisibleCVMarkup(**mode)
    markup.feed(html)
    markup.close()
    return "".join(markup.parts)


# Znaki, których nie przyjmuje lxml (generator Worda, strażnik klauzuli RODO).
# Form feed przechodzi przez bleach wprost, a odwołania liczbowe (`&#12;`)
# zostają w wyniku jako tekst i lxml dekoduje je dopiero u siebie. Zapisana
# z nimi treść kończyła każdy następny zapis błędem 500.
_XML_INCOMPATIBLE = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
_NUMERIC_REFERENCE = re.compile(r"&#(?:[xX]([0-9a-fA-F]{1,8})|([0-9]{1,8}));?")


def _without_incompatible_reference(match: re.Match[str]) -> str:
    code = int(match.group(1), 16) if match.group(1) else int(match.group(2))
    if code > 0x10FFFF or _XML_INCOMPATIBLE.fullmatch(chr(code)):
        return " "
    return match.group(0)


def _sanitized(html: str) -> str:
    """Allowlista z drogą awaryjną: każda próba ma ograniczony koszt."""
    try:
        return _allowlisted(_visible(html))
    except _TreeTooDeep:
        mode = {"flatten": True}
    except _TableMisnested:
        mode = {"flatten": True, "plain_tables": True}
    try:
        return _allowlisted(_visible(html, **mode))
    except _TreeTooCostly:
        pass
    try:
        return _allowlisted(_visible(html, flatten=True, plain_tables=True))
    except _TreeTooCostly:
        # Sam tekst nie ma z czego zbudować drzewa; to ostatnia deska ratunku.
        return _allowlisted(_visible(html, text_only=True))


def sanitize_cv_html(html: str | None) -> str:
    """Zwraca HTML przefiltrowany allowlistą (pusty string dla None)."""
    if not html:
        return ""
    cleaned = _NUMERIC_REFERENCE.sub(_without_incompatible_reference, _sanitized(html))
    return _XML_INCOMPATIBLE.sub(" ", cleaned)
