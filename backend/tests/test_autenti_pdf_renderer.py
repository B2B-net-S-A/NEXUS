"""Unit tests for the WeasyPrint contract HTML→PDF renderer.

These tests require the WeasyPrint native libs (Pango/Cairo/GDK Pixbuf + fonts)
to be installed. The Alpine CI/runtime image provisions ``pango``,
``gdk-pixbuf``, ``font-liberation`` and ``font-dejavu``. On Debian-based local
machines the equivalents are ``libpango-1.0-0``, ``libcairo2``,
``libpangoft2-1.0-0``, ``libgdk-pixbuf-2.0-0``, ``fonts-liberation`` and
``fonts-dejavu``.

Skipped automatically when WeasyPrint can't be imported — keeps fast unit
suites green on developer machines without the native deps.
"""

from __future__ import annotations

import pytest

# Skip the whole module if WeasyPrint isn't installed in this environment.
weasyprint = pytest.importorskip("weasyprint")  # noqa: F841

from app.services.autenti.pdf_renderer import (  # noqa: E402
    _strip_print_script,
    render_contract_pdf,
)


def test_render_returns_pdf_bytes():
    pdf = render_contract_pdf("<p>Hello</p>")
    assert isinstance(pdf, bytes)
    assert pdf.startswith(b"%PDF-")


def test_render_handles_polish_diacritics():
    """żółć ąęść — Latin Extended-A — must round-trip via DejaVu Sans."""
    html = "<h1>Umowa B2B</h1><p>Imię: Żółć Ąęść</p>"
    pdf = render_contract_pdf(html, title="Umowa testowa")
    # Sanity: PDF magic header + non-trivial size (Polish glyphs embed fonts).
    assert pdf.startswith(b"%PDF-")
    assert len(pdf) > 1000

    # Parse the produced PDF and confirm it contains the Polish text. The
    # pdfminer.six dependency is already in requirements.txt.
    from io import BytesIO

    from pdfminer.high_level import extract_text

    text = extract_text(BytesIO(pdf))
    # Different PDF text-extraction backends may normalize whitespace, so
    # check substrings, not equality.
    assert "Umowa B2B" in text
    assert "Imię" in text
    assert "Żółć" in text


def test_render_with_table_html():
    html = (
        "<h2>Strony</h2>"
        "<table><tr><th>Strona</th><th>Nazwa</th></tr>"
        "<tr><td>Zamawiający</td><td>B2BNet</td></tr>"
        "<tr><td>Wykonawca</td><td>JDG Test</td></tr></table>"
    )
    pdf = render_contract_pdf(html)
    assert pdf.startswith(b"%PDF-")


def test_strip_print_script_removes_window_print():
    body = (
        "<head><script>window.addEventListener('load',()=>setTimeout("
        "()=>window.print(),300));</script></head>"
        "<body><p>contract body</p></body>"
    )
    cleaned = _strip_print_script(body)
    assert "window.print" not in cleaned
    assert "<p>contract body</p>" in cleaned


def test_strip_print_script_handles_no_script():
    body = "<p>only body, no script</p>"
    assert _strip_print_script(body) == body


def test_render_strips_print_script_in_pipeline():
    """Auto-print script from `_wrap_printable()` shouldn't leak into PDF."""
    html_with_script = "<script>window.print()</script><p>signed contract body</p>"
    pdf = render_contract_pdf(html_with_script)
    assert pdf.startswith(b"%PDF-")

    from io import BytesIO

    from pdfminer.high_level import extract_text

    text = extract_text(BytesIO(pdf))
    assert "signed contract body" in text
    # Script tag content shouldn't appear as visible text.
    assert "window.print" not in text


def test_render_empty_body_still_produces_pdf():
    """Edge case: empty/None body gracefully renders a 1-page blank PDF."""
    pdf = render_contract_pdf("")
    assert pdf.startswith(b"%PDF-")
