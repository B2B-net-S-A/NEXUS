"""Tekst zamówienia z metadanymi: literowanie spacjami, cap OCR."""

from app.services import order_document_text as m


def test_single_char_token_ratio():
    assert m.single_char_token_ratio("Z a tru d n ie n ie k o n tra k to ra") > 0.5
    assert m.single_char_token_ratio("Zatrudnienie kontraktora - P. Konrad") < 0.3
    assert m.single_char_token_ratio("") == 0.0


def test_letter_spaced_pdf_is_reextracted_with_pdfminer(monkeypatch, tmp_path):
    pdf = tmp_path / "kir.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    monkeypatch.setattr(
        m,
        "extract_text",
        lambda path, filename: "Z a tru d n ie n ie k o n tra k to ra - P . K o n ra d",
    )
    monkeypatch.setattr(
        m, "_pdfminer_text", lambda path: "Zatrudnienie kontraktora - P. Konrad"
    )
    monkeypatch.setattr(m, "_pdf_page_count", lambda path: 1)
    monkeypatch.setattr(m, "_extract_pdf_native", lambda path: "x" * 500)
    doc = m.extract_order_text(str(pdf), "kir.pdf")
    assert doc.text.startswith("Zatrudnienie kontraktora")
    assert doc.reextracted_with == "pdfminer"
    assert doc.letter_spacing_ratio < 0.3
    assert doc.ocr_used is False and doc.ocr_capped is False


def test_reextraction_is_skipped_when_pdfminer_is_not_better(monkeypatch, tmp_path):
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    spaced = "Z a tru d n ie n ie k o n tra k to ra"
    monkeypatch.setattr(m, "extract_text", lambda path, filename: spaced)
    monkeypatch.setattr(m, "_pdfminer_text", lambda path: spaced)
    monkeypatch.setattr(m, "_pdf_page_count", lambda path: 1)
    monkeypatch.setattr(m, "_extract_pdf_native", lambda path: "x" * 500)
    doc = m.extract_order_text(str(pdf), "x.pdf")
    assert doc.reextracted_with is None
    assert doc.text == spaced


def test_ocr_over_page_cap_is_flagged_as_incomplete(monkeypatch, tmp_path):
    """Skan 30 stron: OCR czyta 10 — tekst wygląda poprawnie, ale nie jest kompletny."""
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4 dummy")
    monkeypatch.setattr(
        m, "extract_text", lambda path, filename: "Zamówienie nr 1 " * 50
    )
    monkeypatch.setattr(m, "_pdf_page_count", lambda path: 30)
    monkeypatch.setattr(
        m, "_extract_pdf_native", lambda path: ""
    )  # natywnie pusto → OCR
    doc = m.extract_order_text(str(pdf), "scan.pdf")
    assert doc.ocr_used is True
    assert doc.ocr_capped is True


def test_non_pdf_has_no_pdf_metadata(monkeypatch, tmp_path):
    docx = tmp_path / "z.docx"
    docx.write_bytes(b"PK")
    monkeypatch.setattr(m, "extract_text", lambda path, filename: "Zamówienie nr 7")
    doc = m.extract_order_text(str(docx), "z.docx")
    assert (
        doc.page_count is None
        and doc.ocr_used is False
        and doc.reextracted_with is None
    )
