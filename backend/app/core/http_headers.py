"""HTTP header helpers.

Centralizes RFC 6266 / RFC 5987 safe encoding for ``Content-Disposition``.
HTTP header values must be latin-1 (ISO-8859-1) encodable; a raw filename with
Polish characters (ł, ą, ż, ó…) otherwise crashes ASGI header serialization
with ``UnicodeEncodeError`` — surfacing as a bare HTTP 500. Use this whenever a
download filename is derived from user data (candidate/company names, original
upload names) rather than a constant.
"""

from __future__ import annotations

from urllib.parse import quote

__all__ = ["content_disposition_attachment"]


def content_disposition_attachment(filename: str, fallback: str = "download") -> str:
    """Build a latin-1-safe ``Content-Disposition: attachment`` header value.

    Emits both ``filename="<ascii>"`` (legacy clients) and
    ``filename*=UTF-8''<percent-encoded>`` (RFC 5987, modern browsers) so the
    original name — including non-ASCII characters — survives the download
    without breaking header encoding.
    """
    name = (filename or "").strip() or fallback

    # Legacy token: drop non-ASCII and characters that would break the quoted
    # string (", \, CR, LF). ASCII is a strict subset of latin-1, so this is
    # always header-safe.
    ascii_name = name.encode("ascii", "ignore").decode("ascii")
    for ch in ('"', "\\", "\r", "\n"):
        ascii_name = ascii_name.replace(ch, "")
    ascii_name = ascii_name.strip() or fallback

    # RFC 5987 token: percent-encode everything, always pure ASCII.
    quoted = quote(name, safe="")

    return f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"
