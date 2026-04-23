"""Server-side HTML sanitization for email bodies.

bleach allowlist — strip scripts/styles/event handlers; keep standard
formatting, links (target attr allowed), and images. DOMPurify on the
frontend is the second line of defense.
"""

from __future__ import annotations

import bleach

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


def html_to_text(raw: str) -> str:
    """Plaintext fallback — strip all tags, keep whitespace sensible."""
    if not raw:
        return ""
    return bleach.clean(raw, tags=[], attributes={}, strip=True)
