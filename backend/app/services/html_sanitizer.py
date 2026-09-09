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
- CSS w ``style=`` filtrowany przez CSSSanitizer (bez url(), position:fixed
  itp. nie ma potrzeby blokować — brak skryptów; tniemy tylko do bezpiecznych
  własności prezentacyjnych).

Sanityzujemy NA WYJŚCIU (public share + printable), nie w storage — treść
źródłowa zostaje nienaruszona dla edytora, a polityka może się zaostrzać bez
migracji danych.
"""

from __future__ import annotations

from html.parser import HTMLParser

import bleach
from bleach.css_sanitizer import CSSSanitizer

ALLOWED_TAGS = [
    "a",
    "abbr",
    "article",
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

_CSS_SANITIZER = CSSSanitizer(
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


class _VisibleCVMarkup(HTMLParser):
    """Remove non-visible content before allowlisting presentation markup.

    Bleach strip=True removes a style/script tag but keeps its raw code as text.
    Full-document imports must not print that code in the approved document.
    """

    hidden_tags = {"head", "style", "script", "template", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.hidden = []
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self.hidden_tags:
            self.hidden.append(tag)
        elif not self.hidden:
            self.parts.append(self.get_starttag_text())

    def handle_startendtag(self, tag, attrs):
        if not self.hidden and tag not in self.hidden_tags:
            self.parts.append(self.get_starttag_text())

    def handle_endtag(self, tag):
        if tag in self.hidden:
            del self.hidden[self.hidden.index(tag) :]
        elif not self.hidden and tag not in self.hidden_tags:
            self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)

    def handle_entityref(self, name):
        self.handle_data(f"&{name};")

    def handle_charref(self, name):
        self.handle_data(f"&#{name};")


def sanitize_cv_html(html: str | None) -> str:
    """Zwraca HTML przefiltrowany allowlistą (pusty string dla None)."""
    if not html:
        return ""
    visible = _VisibleCVMarkup()
    visible.feed(html)
    visible.close()
    return bleach.clean(
        "".join(visible.parts),
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRIBUTES,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_CSS_SANITIZER,
        strip=True,
        strip_comments=True,
    )
