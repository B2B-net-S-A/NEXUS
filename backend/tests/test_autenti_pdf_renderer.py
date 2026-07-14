"""Unit tests for the WeasyPrint contract HTML→PDF renderer.

These tests require the WeasyPrint native libs (libpango/libcairo/libgdk-pixbuf
+ fonts) to be installed. CI Docker image already provisions them via the
Dockerfile change in Phase 1.1. Locally: ``apt-get install libpango-1.0-0
libcairo2 libpangoft2-1.0-0 libgdk-pixbuf-2.0-0 fonts-liberation fonts-dejavu``.

Skipped automatically when WeasyPrint can't be imported — keeps fast unit
suites green on developer machines without the native deps.
"""

from __future__ import annotations

import pytest

# Skip the whole module if WeasyPrint isn't installed in this environment.
weasyprint = pytest.importorskip("weasyprint")  # noqa: F841

from app.services.autenti.pdf_renderer import (  # noqa: E402
    _deny_external_resource,
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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:8000/private",
        "http://[::1]/private",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
        "https://example.invalid/tracker.png?secret=do-not-log",
    ],
)
def test_pdf_resource_fetcher_denies_every_url(url):
    response = _deny_external_resource(url)

    try:
        assert response.url == "about:blank"
        assert response.content_type == "image/png"
        assert response.read().startswith(b"\x89PNG\r\n\x1a\n")
        # User-controlled URLs (including query-string secrets) are never
        # copied into the placeholder response.
        assert url not in repr(response)
    finally:
        response.close()


@pytest.mark.parametrize(
    ("source", "base_url", "expected_url"),
    [
        (
            "http://127.0.0.1:8000/private.png",
            None,
            "http://127.0.0.1:8000/private.png",
        ),
        (
            "http://169.254.169.254/latest/meta-data/iam.png",
            None,
            "http://169.254.169.254/latest/meta-data/iam.png",
        ),
        (
            "relative/private.png",
            "http://[::1]/contracts/",
            "http://[::1]/contracts/relative/private.png",
        ),
        (
            "relative/private.png?secret=do-not-log",
            None,
            "relative/private.png?secret=do-not-log",
        ),
    ],
)
def test_render_routes_external_images_only_to_deny_fetcher(
    caplog,
    monkeypatch,
    source,
    base_url,
    expected_url,
):
    """An SSRF payload reaches our deny hook, never a network fetcher."""
    from app.services.autenti import pdf_renderer

    denied: list[str] = []
    real_deny = pdf_renderer._deny_external_resource

    def deny_and_record(url: str):
        denied.append(url)
        return real_deny(url)

    monkeypatch.setattr(pdf_renderer, "_deny_external_resource", deny_and_record)
    caplog.set_level("WARNING", logger="weasyprint")

    pdf = render_contract_pdf(
        f'<p>Safe body</p><img src="{source}" alt="blocked">',
        base_url=base_url,
    )

    assert pdf.startswith(b"%PDF-")
    assert denied == [expected_url]
    assert expected_url not in caplog.text
