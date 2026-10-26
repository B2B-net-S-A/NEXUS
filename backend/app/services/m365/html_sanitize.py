"""Server-side HTML sanitization for email bodies.

bleach allowlist — strip scripts/styles/event handlers; keep standard
formatting, links (target attr allowed), and images. DOMPurify on the
frontend is the second line of defense.
"""

from __future__ import annotations

import bleach
from bleach.css_sanitizer import CSSSanitizer

ALLOWED_TAGS = [
    "a",
    "abbr",
    "b",
    "blockquote",
    "br",
    "code",
    "div",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "i",
    "img",
    "li",
    "ol",
    "p",
    "pre",
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

ALLOWED_ATTRS = {
    "*": ["class", "id", "title"],
    "a": ["href", "target", "rel"],
    "img": ["src", "alt", "width", "height"],
    "td": ["colspan", "rowspan"],
    "th": ["colspan", "rowspan"],
}

# Block javascript: / data: URLs but keep cid: (Outlook inline attachments) +
# https/http/mailto.
ALLOWED_PROTOCOLS = ["http", "https", "mailto", "cid"]


def sanitize_html(raw: str) -> str:
    if not raw:
        return ""
    cleaned = bleach.clean(
        raw,
        tags=ALLOWED_TAGS,
        attributes=ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        strip=True,
        strip_comments=True,
    )
    return cleaned


# Stopka z Outlooka (26.10.2026): bez ``style`` mail wychodził domyślną
# czcionką, z klauzulą RODO jako zbitym blokiem. Dla stopki przepuszczamy
# style z listy (bez ``position``, ``url()`` itp.) i atrybuty układu tabel.
_SIGNATURE_CSS = CSSSanitizer(
    allowed_css_properties=[
        "background-color",
        "border",
        "border-bottom",
        "border-collapse",
        "border-color",
        "border-left",
        "border-right",
        "border-spacing",
        "border-style",
        "border-top",
        "border-width",
        "color",
        "display",
        "font",
        "font-family",
        "font-size",
        "font-style",
        "font-variant",
        "font-weight",
        "height",
        "letter-spacing",
        "line-height",
        "margin",
        "margin-bottom",
        "margin-left",
        "margin-right",
        "margin-top",
        "max-width",
        "padding",
        "padding-bottom",
        "padding-left",
        "padding-right",
        "padding-top",
        "text-align",
        "text-decoration",
        "text-indent",
        "text-transform",
        "vertical-align",
        "white-space",
        "width",
    ]
)

SIGNATURE_ALLOWED_TAGS = [*ALLOWED_TAGS, "font"]

SIGNATURE_ALLOWED_ATTRS = {
    "*": ["class", "id", "title", "style", "align"],
    "a": ["href", "target", "rel"],
    "img": ["src", "alt", "width", "height", "border"],
    "font": ["face", "color", "size"],
    "table": ["width", "border", "cellpadding", "cellspacing"],
    "td": ["colspan", "rowspan", "width", "valign"],
    "th": ["colspan", "rowspan", "width", "valign"],
}


def sanitize_signature_html(raw: str) -> str:
    if not raw:
        return ""
    return bleach.clean(
        raw,
        tags=SIGNATURE_ALLOWED_TAGS,
        attributes=SIGNATURE_ALLOWED_ATTRS,
        protocols=ALLOWED_PROTOCOLS,
        css_sanitizer=_SIGNATURE_CSS,
        strip=True,
        strip_comments=True,
    )


def html_to_text(raw: str) -> str:
    """Plaintext fallback — strip all tags, keep whitespace sensible."""
    if not raw:
        return ""
    return bleach.clean(raw, tags=[], attributes={}, strip=True)
