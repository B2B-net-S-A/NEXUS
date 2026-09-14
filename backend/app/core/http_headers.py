"""HTTP header helpers.

Centralizes RFC 6266 / RFC 5987 safe encoding for ``Content-Disposition``.
HTTP header values must be latin-1 (ISO-8859-1) encodable; a raw filename with
Polish characters (ł, ą, ż, ó…) otherwise crashes ASGI header serialization
with ``UnicodeEncodeError`` — surfacing as a bare HTTP 500. Use this whenever a
download filename is derived from user data (candidate/company names, original
upload names) rather than a constant.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import quote

__all__ = ["content_disposition", "content_disposition_attachment"]


def content_disposition(
    filename: str,
    disposition: Literal["attachment", "inline"] = "attachment",
    fallback: str = "download",
) -> str:
    """Build a latin-1-safe ``Content-Disposition`` header value.

    Emits both ``filename="<ascii>"`` (legacy clients) and
    ``filename*=UTF-8''<percent-encoded>`` (RFC 5987, modern browsers) so the
    original name — including non-ASCII characters — survives the download
    without breaking header encoding.

    ``disposition`` controls whether the browser saves the file (``attachment``)
    or renders it inline in the current tab (``inline`` — used for PDF/image
    previews).
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

    return f"{disposition}; filename=\"{ascii_name}\"; filename*=UTF-8''{quoted}"


def content_disposition_attachment(filename: str, fallback: str = "download") -> str:
    """Backwards-compatible alias for ``content_disposition(..., "attachment")``."""
    return content_disposition(filename, "attachment", fallback)


_CREDENTIAL_HEADERS = ("authorization", "x-api-key", "x-impersonate-user-id")


def apply_credentialed_cache_policy(request_headers, response_headers) -> None:
    """Keep responses to credentialed requests out of shared browser caches.

    ``FileResponse`` sends ``ETag`` + ``Last-Modified`` and no
    ``Cache-Control``, so browsers cached order PDFs heuristically and later
    served them to a request WITHOUT a token, or to a different user previewed
    in the same browser (UAT M07-B01). An API answer to a request carrying
    credentials is per-user by definition.

    * ``Cache-Control: private, no-store`` is only a DEFAULT — endpoints that
      deliberately set their own policy (e.g. ``private, max-age=60``) keep it.
    * ``Vary`` always gains the credential headers, so even such a deliberate
      short cache is keyed per token instead of per URL.
    """
    if not any(name in request_headers for name in _CREDENTIAL_HEADERS):
        return
    if "cache-control" not in response_headers:
        response_headers["Cache-Control"] = "private, no-store"
    existing = response_headers.get("vary", "")
    present = {part.strip().lower() for part in existing.split(",") if part.strip()}
    if "*" in present:
        return
    missing = [
        header
        for header in ("Authorization", "X-API-Key", "X-Impersonate-User-Id")
        if header.lower() not in present
    ]
    if missing:
        response_headers["Vary"] = ", ".join(
            [part.strip() for part in existing.split(",") if part.strip()] + missing
        )
