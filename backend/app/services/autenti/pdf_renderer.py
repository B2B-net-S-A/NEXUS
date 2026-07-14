"""HTML → PDF rendering for Autenti contract uploads.

The contract draft body is plain HTML+CSS produced by Tiptap (per
:mod:`app.api.contracts`). Autenti API v2 requires PDF for ``files`` upload
(HTML is not supported), so we run WeasyPrint server-side. Sync function
must be called via :func:`asyncio.to_thread` from async code paths.

Why WeasyPrint (plan §1):
- ARM image weight ~80 MB vs ~250 MB for headless Chromium.
- Existing print CSS (``body{font-family,max-width,line-height}``,
  simple ``table``, ``@media print``) is fully covered.
- No subprocess / browser pool.

Polish characters: ``fonts-liberation`` + ``fonts-dejavu`` apt packages
cover Latin Extended-A. Verified by ``test_autenti_pdf_renderer.py``.
"""

from __future__ import annotations

import base64
import logging
import re
from html import escape
from typing import Optional

from app.services.m365.html_sanitize import sanitize_html

logger = logging.getLogger(__name__)

# Inline ``<script>`` tags trigger neither functionality nor warnings in
# WeasyPrint (it ignores them silently), but stripping them keeps the source
# clean and avoids confusing future readers who think client JS could run.
_SCRIPT_RE = re.compile(r"<script\b[^>]*>.*?</script\s*>", re.IGNORECASE | re.DOTALL)

# A valid 1x1 transparent PNG.  Returning a harmless local response instead of
# raising prevents WeasyPrint from logging the attacker-controlled source URL.
_TRANSPARENT_PIXEL = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42Y"
    "AAAAASUVORK5CYII="
)


def _deny_external_resource(url: str) -> object:
    """Block every resource lookup initiated by contract HTML.

    Contract drafts are user-editable and self-contained.  Letting WeasyPrint
    use its default fetcher would therefore turn ``<img src=...>`` into a
    server-side HTTP or file request.  We replace every lookup with one local,
    transparent pixel so rendering can continue without network or filesystem
    access.

    The URL is deliberately omitted from the response: it can contain a
    user-controlled query string and must not leak into application logs.  The
    lazy import preserves this module's existing lightweight import behavior.
    """
    del url
    from weasyprint.urls import URLFetcherResponse  # noqa: WPS433

    return URLFetcherResponse(
        "about:blank",
        body=_TRANSPARENT_PIXEL,
        headers={"Content-Type": "image/png"},
        status=200,
    )


def _strip_print_script(html: str) -> str:
    """Remove ``<script>window.print()</script>`` tags from the printable HTML.

    The ``_wrap_printable()`` helper at ``app/api/contracts.py:599-617``
    auto-injects a JS line that triggers the OS print dialog when the HTML
    is opened in a browser. Useless (and noisy) when rendering server-side.
    """
    return _SCRIPT_RE.sub("", html)


def _wrap_for_pdf(body_html: str, title: str) -> str:
    """Wrap raw body HTML in a print-ready document.

    Mirrors ``_wrap_printable()`` from ``app/api/contracts.py`` but drops
    the auto-print script and tweaks margins for A4. Identical CSS rules
    so the visual output matches what the recruiter sees in the print
    preview.
    """
    safe_title = escape(title)
    safe_body = sanitize_html(body_html)
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8">'
        f"<title>{safe_title}</title>"
        "<style>"
        "@page{size:A4;margin:18mm 16mm}"
        "body{font-family:'DejaVu Sans','Liberation Sans',Helvetica,Arial,"
        "sans-serif;line-height:1.55;color:#222}"
        "h1,h2,h3{color:#111}"
        "table{border-collapse:collapse;width:100%;margin:1em 0}"
        "th,td{border:1px solid #ccc;padding:6px 10px;text-align:left;"
        "vertical-align:top}"
        "</style></head><body>"
        f"{safe_body}"
        "</body></html>"
    )


def render_contract_pdf(
    html: str,
    *,
    title: str = "Umowa",
    base_url: Optional[str] = None,
) -> bytes:
    """Render contract HTML body to a PDF byte stream.

    Synchronous — wrap with :func:`asyncio.to_thread` from async callers.
    The signature accepts the raw Tiptap body HTML (without ``<html>`` /
    ``<body>`` wrap); we add the print-ready shell internally so callers
    don't reimplement it.

    Args:
        html: Raw body HTML from ``contracts.draft_content_html``.
        title: PDF document title (shown in viewer title bar).
        base_url: Optional base URL for resolving relative ``<img>`` /
            ``<link>``. Drafts are self-contained, so a missing value is
            replaced with the non-network ``about:blank/`` base.

    Returns:
        PDF byte stream starting with ``b"%PDF-"``.

    Raises:
        ImportError: WeasyPrint not installed (Dockerfile apt deps missing).
        Exception: WeasyPrint internal errors propagate as-is.
    """
    # Lazy import — WeasyPrint pulls heavy native libs at module load. Tests
    # that don't exercise PDF generation should not pay this cost.
    from weasyprint import HTML  # noqa: WPS433 (intentional lazy import)

    cleaned = _strip_print_script(html or "")
    document = _wrap_for_pdf(cleaned, title=title)
    # WeasyPrint logs an unresolved relative URL before calling ``url_fetcher``
    # when ``base_url`` is ``None``.  Supplying a constant, non-network base
    # keeps it out of that warning path; depending on the WeasyPrint version,
    # the deny fetcher receives either the relative value or an ``about:`` URL
    # and discards both without performing any I/O.
    effective_base_url = base_url or "about:blank/"
    pdf_bytes = HTML(
        string=document,
        base_url=effective_base_url,
        url_fetcher=_deny_external_resource,
    ).write_pdf()
    if pdf_bytes is None:
        # WeasyPrint returns None when target=None and no output_path —
        # we always pass string-based input so this is defensive.
        raise RuntimeError("WeasyPrint returned no PDF bytes")
    logger.debug(
        "Rendered contract PDF: title=%r, body_len=%d, pdf_len=%d",
        title,
        len(cleaned),
        len(pdf_bytes),
    )
    return pdf_bytes
