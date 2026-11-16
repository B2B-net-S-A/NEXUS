"""PDF faktury do załącznika e-faktury (wizualizacja z XML-a FA)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.peppol import fa_reader, pdf

DATA = Path(__file__).parent / "data" / "peppol"


def _weasyprint_or_skip() -> None:
    try:
        import weasyprint  # noqa: F401
    except (ImportError, OSError) as exc:  # brak Pango poza obrazem Dockera
        pytest.skip(f"WeasyPrint niedostępny: {exc}")


def test_renders_invoice_pdf_with_lines_and_ksef_number():
    _weasyprint_or_skip()
    doc = fa_reader.read((DATA / "fa_nordea_rabat_ae.xml").read_bytes())

    content = pdf.render(doc, ksef_number="9876543210-20261106-0A0B0C0D0E0F-11")

    assert content.startswith(b"%PDF-")
    assert len(content) > 2000


def test_filename_is_safe():
    assert pdf.filename("231/11/2026/UE") == "231_11_2026_UE.pdf"
    assert pdf.filename("") == "faktura.pdf"
