"""Runda 9 (R9-N7-2): odczyt PDF w procesie z limitem pamięci i czasu.

„Bomba” PDF (strumień, który rozwija się do gigabajtów) wgrana z formularza
kariery albo z poczty zamówień zabijała cały backend — pdfminer dekompresuje
strumienie bez limitu, a pdf2image renderował strony w rozmiarze z MediaBox.
"""

from __future__ import annotations

import sys
import time
import zlib
from types import SimpleNamespace

import pytest

from app.services import cv_text_extractor as cte


def _pdf(content: bytes, *, compress: bool = False) -> bytes:
    """Minimalny PDF z jedną stroną i podanym strumieniem treści."""
    stream_dict = b"<< /Length %d >>" % len(content)
    if compress:
        stream_dict = b"<< /Length %d /Filter /FlateDecode >>" % len(content)
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842]"
        b" /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        stream_dict + b"\nstream\n" + content + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = bytearray(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    for offset in offsets:
        out += b"%010d 00000 n \n" % offset
    out += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        xref,
    )
    return bytes(out)


def _text_pdf(tmp_path) -> str:
    content = b"".join(
        b"BT /F1 12 Tf 50 %d Td (Senior Python Developer line %d) Tj ET\n"
        % (800 - 20 * i, i)
        for i in range(12)
    )
    path = tmp_path / "abcd1234-Jan_Kowalski_CV.pdf"
    path.write_bytes(_pdf(content))
    return str(path)


def test_pdf_is_read_in_the_worker_process(tmp_path):
    path = _text_pdf(tmp_path)
    out = cte.extract_text(path, "Jan_Kowalski_CV.pdf")
    assert "Senior Python Developer line 3" in out


def test_order_document_helpers_go_through_the_worker(tmp_path):
    from app.services import order_document_text as odt

    assert odt._extract_pdf_native is cte.extract_pdf_native_sandboxed
    path = _text_pdf(tmp_path)
    assert odt._pdf_page_count(path) == 1
    assert "Senior Python Developer" in (odt._pdfminer_text(path) or "")


def test_worker_timeout_returns_nothing_instead_of_hanging(tmp_path, monkeypatch):
    path = _text_pdf(tmp_path)
    monkeypatch.setattr(
        cte,
        "_pdf_worker_command",
        lambda op, p: [sys.executable, "-c", "import time; time.sleep(30)"],
    )
    started = time.monotonic()
    assert cte._run_pdf_worker("pdf", path, timeout=1) is None
    assert time.monotonic() - started < 10


def test_worker_crash_degrades_to_empty_text(tmp_path, monkeypatch):
    path = _text_pdf(tmp_path)
    monkeypatch.setattr(
        cte,
        "_pdf_worker_command",
        lambda op, p: [sys.executable, "-c", "raise MemoryError"],
    )
    assert cte.extract_text(path, "cv.pdf") == ""


@pytest.mark.skipif(
    not sys.platform.startswith("linux"), reason="RLIMIT_AS działa tylko na Linuksie"
)
def test_decompression_bomb_is_stopped_by_the_memory_limit(tmp_path):
    # ~600 MB treści po dekompresji w kilkuset kilobajtach pliku.
    comp = zlib.compressobj(9)
    chunk = b" " * (1 << 20)
    body = bytearray(comp.compress(b"BT /F1 12 Tf 50 800 Td (Senior) Tj ET\n"))
    for _ in range(600):
        body += comp.compress(chunk)
    body += comp.flush()
    path = tmp_path / "bomb.pdf"
    path.write_bytes(_pdf(bytes(body), compress=True))

    started = time.monotonic()
    result = cte._run_pdf_worker(
        "native", str(path), timeout=60, memory_bytes=384 * 1024 * 1024
    )
    assert result is None  # proces odczytu padł na limicie, web proces żyje
    assert time.monotonic() - started < 60


def test_ocr_render_is_bounded_in_size_and_kept_on_disk(monkeypatch, tmp_path):
    seen: dict = {}

    def convert_from_path(path, **kwargs):
        seen.update(kwargs)
        return ["page"]

    monkeypatch.setitem(
        sys.modules, "pdf2image", SimpleNamespace(convert_from_path=convert_from_path)
    )
    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=lambda img, lang: "tekst ze skanu"),
    )
    assert cte._extract_pdf_ocr(str(tmp_path / "scan.pdf")) == "tekst ze skanu"
    assert seen["size"] == cte._OCR_PAGE_MAX_PX
    assert seen["output_folder"]
    assert seen["last_page"] == 10


def test_worker_output_is_capped(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", lambda p: "x" * 10)
    monkeypatch.setattr(cte, "_PDF_WORKER_MAX_CHARS", 4)
    monkeypatch.setattr(cte, "_apply_worker_limits", lambda: None)
    assert cte._worker_main(["pdf", str(tmp_path / "a.pdf")]) == 0
    assert '"xxxx"' in capsys.readouterr().out
    assert cte._worker_main(["rm", "-rf"]) == 2
