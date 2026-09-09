"""OCR must not silently discard employment on later pages."""

import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.cv_generator_b2b import text_extractor as extractor


@pytest.mark.parametrize("broken_page", [None, 11])
def test_ocr_reads_beyond_ten_pages_or_rejects_incomplete_source(
    monkeypatch, broken_page
):
    images = []

    def render(data, *, first_page, last_page, dpi, timeout):
        assert first_page == last_page
        assert 0 < timeout <= 30
        if first_page == broken_page:
            raise RuntimeError("page conversion failed")
        image = SimpleNamespace(page=first_page, close=Mock())
        images.append(image)
        return [image]

    def ocr(image, *, lang, timeout):
        assert 0 < timeout <= 30
        return f"Employment on page {image.page}"

    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        SimpleNamespace(
            pdfinfo_from_bytes=lambda *args, **kwargs: {"Pages": 12},
            convert_from_bytes=render,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "pytesseract", SimpleNamespace(image_to_string=ocr)
    )
    if broken_page:
        with pytest.raises(extractor.CVTextExtractionError, match="wszystkich stron"):
            extractor._extract_pdf_ocr(b"synthetic scan")
    else:
        result = extractor._extract_pdf_ocr(b"synthetic scan")
        assert result.split("\n\n") == [f"Employment on page {n}" for n in range(1, 13)]
    for image in images:
        image.close.assert_called_once()


def test_ocr_deadline_rejects_instead_of_returning_partial_text(monkeypatch):
    render = Mock()
    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        SimpleNamespace(
            pdfinfo_from_bytes=lambda *args, **kwargs: {"Pages": 12},
            convert_from_bytes=render,
        ),
    )
    monkeypatch.setitem(
        sys.modules, "pytesseract", SimpleNamespace(image_to_string=Mock())
    )
    monkeypatch.setattr(extractor.time, "monotonic", Mock(side_effect=[0, 121]))
    with pytest.raises(extractor.CVTextExtractionError):
        extractor._extract_pdf_ocr(b"synthetic scan")
    render.assert_not_called()
