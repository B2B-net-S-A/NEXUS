"""OCR must not silently discard employment on later pages."""

import sys
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app.services.cv_generator_b2b import text_extractor as extractor


@pytest.mark.parametrize(
    "failure",
    [subprocess.TimeoutExpired("pdftotext", 30), OSError("reader unavailable")],
)
def test_native_reader_failure_uses_complete_fallback(monkeypatch, failure):
    monkeypatch.setattr(extractor, "_extract_mixed_pdf", lambda data: None)
    monkeypatch.setattr(extractor.shutil, "which", lambda name: "/bin/pdftotext")
    reader = Mock(side_effect=failure)
    monkeypatch.setattr(extractor.subprocess, "run", reader)
    full_text = "\n".join(f"Employer {i}: source employment history" for i in range(12))
    fallback = Mock(return_value=full_text)
    monkeypatch.setattr(extractor, "_extract_pdf_pdfplumber", fallback)
    ocr = Mock(side_effect=AssertionError("Complete native text needs no OCR"))
    monkeypatch.setattr(extractor, "_extract_pdf_ocr", ocr)

    assert extractor.extract_text_from_file(b"synthetic PDF", "cv.pdf") == full_text
    fallback.assert_called_once_with(b"synthetic PDF")
    ocr.assert_not_called()


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


def test_mixed_pdf_preserves_native_pages_and_ocr_order(monkeypatch):
    from contextlib import nullcontext

    native = "Original searchable employment history. " * 10
    pages = [
        SimpleNamespace(images=[], extract_text=lambda: native),
        SimpleNamespace(images=[{}], extract_text=lambda: "Page 2"),
    ]
    import pdfplumber

    monkeypatch.setattr(
        pdfplumber, "open", lambda *args: nullcontext(SimpleNamespace(pages=pages))
    )
    ocr = Mock(return_value=native + "\n\nEarlier scanned employment")
    monkeypatch.setattr(extractor, "_extract_pdf_ocr", ocr)
    ordinary = Mock(side_effect=AssertionError("Must not return just searchable page"))
    monkeypatch.setattr(extractor, "_extract_pdf_pdftotext", ordinary)
    result = extractor.extract_text_from_file(b"mixed", "cv.pdf")
    assert result.endswith("Earlier scanned employment")
    ocr.assert_called_once_with(b"mixed", native_pages={1: native})
    ordinary.assert_not_called()


def test_ocr_keeps_native_text_without_rendering_its_page(monkeypatch):
    image = SimpleNamespace(close=Mock())
    render = Mock(return_value=[image])
    monkeypatch.setitem(
        sys.modules,
        "pdf2image",
        SimpleNamespace(
            pdfinfo_from_bytes=lambda *args, **kwargs: {"Pages": 2},
            convert_from_bytes=render,
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(
            image_to_string=Mock(return_value="Scanned employer"),
        ),
    )
    result = extractor._extract_pdf_ocr(
        b"mixed", native_pages={1: "Exact native employer"}
    )
    assert result == "Exact native employer\n\nScanned employer"
    assert render.call_count == 1
    assert render.call_args.kwargs["first_page"] == 2
    image.close.assert_called_once()
