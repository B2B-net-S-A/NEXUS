"""Unit tests for CV text extractor.

Verifies dispatch by file extension, graceful handling of unsupported formats,
and whitespace normalization. Heavy-lift libraries (pdfminer, python-docx) are
mocked — we test our dispatch logic, not third-party correctness.
"""

from __future__ import annotations

import os
import tempfile

import pytest


def test_extract_text_dispatches_to_pdfminer_for_pdf(monkeypatch):
    from app.services import cv_text_extractor as cte

    called_with: dict[str, str] = {}

    def _fake_pdf_extract(path: str) -> str:
        called_with["path"] = path
        return "Senior Python Developer\n\nExperience: 10 years."

    monkeypatch.setattr(cte, "_extract_pdf", _fake_pdf_extract)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "resume.pdf")
        assert "Senior Python Developer" in out
        assert "10 years" in out
        assert called_with["path"] == path
    finally:
        os.unlink(path)


def test_extract_text_dispatches_to_docx_for_docx(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Jan Kowalski\nLead Engineer")
    with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.docx")
        assert "Jan Kowalski" in out
        assert "Lead Engineer" in out
    finally:
        os.unlink(path)


def test_extract_text_dispatches_to_docx_for_doc(monkeypatch):
    """Legacy .doc uses same python-docx path (best-effort)."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "content")
    with tempfile.NamedTemporaryFile(suffix=".doc", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.doc")
        assert out == "content"
    finally:
        os.unlink(path)


def test_extract_text_txt_reads_raw_content():
    from app.services import cv_text_extractor as cte

    content = "Marek Nowak\n\nSenior Backend Developer\n\n5 years Python."
    with tempfile.NamedTemporaryFile(
        suffix=".txt", delete=False, mode="w", encoding="utf-8"
    ) as f:
        f.write(content)
        path = f.name
    try:
        out = cte.extract_text(path, "cv.txt")
        assert "Marek Nowak" in out
        assert "5 years Python" in out
    finally:
        os.unlink(path)


def test_extract_text_unsupported_extension_raises():
    from app.services import cv_text_extractor as cte

    with tempfile.NamedTemporaryFile(suffix=".rtf", delete=False) as f:
        path = f.name
    try:
        with pytest.raises(cte.UnsupportedCvFormat):
            cte.extract_text(path, "cv.rtf")
    finally:
        os.unlink(path)


def test_extract_text_case_insensitive_extension(monkeypatch):
    """Real-world uploads often have .PDF or .DOCX uppercase."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "pdf content")
    with tempfile.NamedTemporaryFile(suffix=".PDF", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "CV.PDF")
        assert out == "pdf content"
    finally:
        os.unlink(path)


def test_extract_text_normalizes_whitespace(monkeypatch):
    from app.services import cv_text_extractor as cte

    noisy = "   \n\n\n  Hello   world  \n\n\n  Second   line \t\t end  \n\n"
    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: noisy)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.pdf")
        # no leading/trailing whitespace
        assert out == out.strip()
        # single-newline runs preserved, not triple-blank runs
        assert "\n\n\n" not in out
        # collapsed horizontal whitespace
        assert "Hello world" in out
        assert "Second line end" in out
    finally:
        os.unlink(path)


def test_extract_text_extractor_returning_none_yields_empty(monkeypatch):
    """If pdfminer returns None (corrupt PDF edge case), graceful empty string."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: None)
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        path = f.name
    try:
        out = cte.extract_text(path, "cv.pdf")
        assert out == ""
    finally:
        os.unlink(path)


def test_extract_text_filename_dispatch_fallback(monkeypatch):
    """When file has no extension on disk, fall back to filename extension."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "ok")
    with tempfile.NamedTemporaryFile(delete=False) as f:
        path = f.name  # no suffix
    try:
        out = cte.extract_text(path, "resume.pdf")
        assert out == "ok"
    finally:
        os.unlink(path)


def test_normalize_drops_nul_bytes():
    """Postgres odrzuca 0x00 w tekście; ekstraktor ma go wyciąć zanim trafi do DB."""
    from app.services.cv_text_extractor import _normalize

    assert _normalize("Jan\x00 Kowalski\x00\n\x00Python") == "Jan Kowalski\nPython"


# ── Format from the bytes, not the name (2026-09-22) ─────────────────────────


def _write(suffix: str, data: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as f:
        f.write(data)
        return f.name


def test_pdf_saved_as_docx_is_read_as_pdf(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "PDF text")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "docx text")
    path = _write(".docx", b"%PDF-1.7\n...")
    try:
        assert cte.extract_text(path, "CV Jan.docx") == "PDF text"
    finally:
        os.unlink(path)


def test_pdf_saved_as_odt_is_read_instead_of_rejected(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_pdf", lambda _p: "PDF text")
    path = _write(".odt", b"%PDF-1.4\n...")
    try:
        assert cte.extract_text(path, "cv.odt") == "PDF text"
    finally:
        os.unlink(path)


def test_real_docx_and_unknown_bytes_keep_the_declared_format(monkeypatch):
    import io
    import zipfile

    from app.services import cv_text_extractor as cte

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("word/document.xml", "<w:document/>")
    docx = _write(".docx", buf.getvalue())
    txt = _write(".txt", b"plain text CV")
    try:
        assert cte.sniff_extension(docx) == ".docx"
        assert cte.sniff_extension(txt) is None
        assert cte.extract_text(txt, "cv.txt") == "plain text CV"
    finally:
        os.unlink(docx)
        os.unlink(txt)


def test_zip_that_is_not_word_is_not_called_docx():
    import io
    import zipfile

    from app.services import cv_text_extractor as cte

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("content.xml", "<office/>")
    path = _write(".odt", buf.getvalue())
    try:
        assert cte.sniff_extension(path) is None
    finally:
        os.unlink(path)


# ── Sklejony tekst (słowa bez przerw) ─────────────────────────────────────────

_GLUED = "ledtheqainitiativeandthedevelopmentofunittestingtoolforcobolprograms " * 8
_SPACED = "led the qa initiative and the development of unit testing tool " * 8


class _FakePage:
    def __init__(self, default):
        self.default = default

    def extract_text(self, **kwargs):
        return _SPACED if kwargs.get("x_tolerance") == 1 else self.default


class _FakePdf:
    def __init__(self, default):
        self.pages = [_FakePage(default)]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_pdfplumber(monkeypatch, default):
    import sys
    import types

    module = types.ModuleType("pdfplumber")
    module.open = lambda _path: _FakePdf(default)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "pdfplumber", module)


def test_looks_glued_is_about_word_length_not_text_length():
    from app.services.cv_text_extractor import looks_glued

    assert looks_glued(_GLUED)
    assert not looks_glued(_SPACED)
    assert not looks_glued("krótkiCVbezprzerw"), "krótkich tekstów nie oceniamy"
    assert not looks_glued(None)


def test_glued_pdf_is_read_again_with_tighter_letter_gap(monkeypatch):
    """Produkcja 23.09.2026: 1 581 CV z tekstem bez spacji — domyślny próg
    pdfplumbera (3 pt) nie widział odstępu między słowami w ciasnym kerningu."""
    from app.services import cv_text_extractor as cte

    _fake_pdfplumber(monkeypatch, _GLUED)
    out = cte._extract_pdf_native("/tmp/x.pdf")
    assert "the qa initiative" in out


def test_well_spaced_pdf_keeps_the_default_read(monkeypatch):
    from app.services import cv_text_extractor as cte

    normal = "Senior QA Engineer with Selenium and Python experience. " * 10
    _fake_pdfplumber(monkeypatch, normal)
    assert cte._extract_pdf_native("/tmp/x.pdf") == normal


def _fake_contract_pdf(monkeypatch, page_texts):
    import types

    from app.services import cv_text_extractor as cte

    class _Page:
        def __init__(self, text):
            self._text = text

        def extract_text(self, **_kwargs):
            return self._text

        def close(self):
            pass

    class _Pdf:
        pages = [_Page(text) for text in page_texts]

        def __enter__(self):
            return self

        def __exit__(self, *_exc):
            return False

    monkeypatch.setitem(
        __import__("sys").modules,
        "pdfplumber",
        types.SimpleNamespace(open=lambda _path: _Pdf()),
    )
    return cte


def test_all_pages_ocr_reads_only_pages_without_text(monkeypatch):
    """Aneks NBP z paczki: 4 strony tekstu i 9 stron skanu w jednym PDF-ie."""
    long_text = "Paragraf umowy z treścią, która jest prawdziwym tekstem strony PDF."
    cte = _fake_contract_pdf(monkeypatch, [long_text, "", long_text, "12"])
    scanned: list[int] = []

    def _ocr(_path, number):
        scanned.append(number)
        return f"Tekst ze skanu strony numer {number}"

    monkeypatch.setattr(cte, "_ocr_one_page", _ocr)
    result = cte._worker_all_pages("umowa.pdf")

    assert scanned == [2, 4]
    assert result["pages"] == 4 and result["ocr_pages"] == 2
    assert "Tekst ze skanu strony numer 2" in result["text"]
    assert result["text"].count(long_text) == 2


def test_all_pages_ocr_does_not_stop_at_ten_pages(monkeypatch):
    cte = _fake_contract_pdf(monkeypatch, [""] * 23)
    monkeypatch.setattr(
        cte, "_ocr_one_page", lambda _p, n: f"Strona skanu {n} z tekstem"
    )
    result = cte._worker_all_pages("skan.pdf")
    assert result["ocr_pages"] == 23
    assert "Strona skanu 23 z tekstem" in result["text"]


def test_all_pages_failed_ocr_keeps_the_rest_of_the_document(monkeypatch):
    cte = _fake_contract_pdf(
        monkeypatch, ["", "Tekst drugiej strony, całkiem długi zapis."]
    )

    def _ocr(_path, _number):
        raise RuntimeError("tesseract")

    monkeypatch.setattr(cte, "_ocr_one_page", _ocr)
    result = cte._worker_all_pages("umowa.pdf")
    assert result["ocr_pages"] == 0
    assert "Tekst drugiej strony" in result["text"]


def test_all_pages_timeout_grows_with_pages_up_to_a_ceiling():
    from app.services import cv_text_extractor as cte

    assert cte.all_pages_timeout(None) == 150
    assert cte.all_pages_timeout(248) == 150 + 2480
    assert cte.all_pages_timeout(10_000) == 3600


def test_all_pages_sandboxed_returns_none_when_worker_gives_up(monkeypatch):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: None)
    assert cte.extract_pdf_all_pages_sandboxed("umowa.pdf") is None


# ── Word bez tekstu z python-docx (03.11.2026) ───────────────────────────────
#
# Binarny `.doc` python-docx odrzuca zawsze, a tekst w polach tekstowych
# i kontrolkach pomija, więc `/from-cv` odpowiadał 400 i zgłoszenie z portalu
# przepadało. Na kopii produkcji LibreOffice odczytał 65 z 65 takich `.doc`
# i 28 z 28 takich `.docx`.


@pytest.fixture
def word_file(tmp_path):
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 binarny Word")
    return str(path)


@pytest.fixture
def libreoffice(monkeypatch):
    """Proces odczytu udany: zwraca wywołane operacje, tekst podaje test."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    calls: list[str] = []

    def _worker(op, _path, **_kwargs):
        calls.append(op)
        return {"text": "Tekst z LibreOffice. " * 10}

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_run_pdf_worker", _worker)
    return calls


def test_word_python_docx_cannot_read_is_read_through_libreoffice(
    monkeypatch, word_file, libreoffice
):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    assert cte.extract_text(word_file, "cv.doc").startswith("Tekst z LibreOffice.")
    assert libreoffice == ["word"]


def test_word_with_empty_body_is_read_through_libreoffice(
    monkeypatch, word_file, libreoffice
):
    """Cała treść w polach tekstowych: python-docx nie zgłasza błędu, tylko pustkę."""
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "")
    assert cte.extract_text(word_file, "cv.docx").startswith("Tekst z LibreOffice.")


def test_word_with_body_text_does_not_start_libreoffice(
    monkeypatch, word_file, libreoffice
):
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Doświadczenie " * 20)
    assert cte.extract_text(word_file, "cv.docx").startswith("Doświadczenie")
    assert libreoffice == []


def test_word_worker_gets_the_memory_libreoffice_needs(monkeypatch, word_file):
    """Przy limicie z PDF-a (1,5 GB) prawdziwe CV wywracało LibreOffice sygnałem 11."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, int] = {}

    def _worker(_op, _path, *, memory_bytes):
        seen["memory_bytes"] = memory_bytes
        return {"text": "Tekst z LibreOffice"}

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _worker)
    cte.extract_text(word_file, "cv.doc")
    assert seen["memory_bytes"] == cte.WORD_WORKER_MEMORY_BYTES
    assert cte.WORD_WORKER_MEMORY_BYTES > cte.PDF_WORKER_MEMORY_BYTES


def test_word_short_text_stays_when_libreoffice_gives_less(monkeypatch, word_file):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: "Krótka treść pliku")
    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: {"text": "x"})
    assert cte.extract_text(word_file, "cv.docx") == "Krótka treść pliku"


def test_word_worker_failure_keeps_empty_text(monkeypatch, word_file):
    """Limit czasu albo pamięci: pusty tekst jak dotąd, bez wyjątku."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", lambda *_a, **_k: None)
    assert cte.extract_text(word_file, "cv.doc") == ""


def test_word_without_libreoffice_does_not_start_the_worker(monkeypatch, word_file):
    """Lokalnie i w CI LibreOffice'a nie ma: wynik jak przed zmianą."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_worker(*_a, **_k):
        raise AssertionError("bez LibreOffice proces odczytu nie ma czego zrobić")

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: None)
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _no_worker)
    assert cte.extract_text(word_file, "cv.doc") == ""


def test_word_conversions_wait_for_a_free_slot(monkeypatch, word_file):
    """LibreOffice to ciężki proces: gdy miejsce zajęte, pusty tekst zamiast tłoku."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_worker(*_a, **_k):
        raise AssertionError("zajęte miejsce nie uruchamia drugiej zamiany")

    monkeypatch.setattr(cv_pdf_preview, "soffice_path", lambda: "/usr/bin/soffice")
    monkeypatch.setattr(cte, "_extract_docx", lambda _p: None)
    monkeypatch.setattr(cte, "_run_pdf_worker", _no_worker)
    monkeypatch.setattr(cte, "_WORD_SLOT_WAIT_SECONDS", 0.01)
    assert cte._word_slot.acquire(blocking=False)
    try:
        assert cte.extract_text(word_file, "cv.doc") == ""
    finally:
        cte._word_slot.release()


def test_word_zip_bomb_never_reaches_libreoffice(monkeypatch, tmp_path):
    """Strażnik z `_extract_docx` połyka wyjątek, więc proces odczytu sprawdza sam."""
    import zipfile

    from app.core import zip_guard
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_conversion(*_a, **_k):
        raise AssertionError("bomba ZIP nie może dojść do LibreOffice")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _no_conversion)
    monkeypatch.setattr(zip_guard, "MAX_XML_PART_UNCOMPRESSED", 10)
    path = tmp_path / "bomba.docx"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("word/document.xml", "<w:document>" + "x" * 100)
    assert cte._worker_word(str(path)) is None


def test_word_worker_reads_the_converted_pdf(monkeypatch, tmp_path):
    """Wynik zamiany idzie zwykłą ścieżką PDF-a, więc skan w Wordzie dostaje OCR."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, bytes] = {}

    def _read_pdf(path):
        with open(path, "rb") as handle:
            seen["pdf"] = handle.read()
        return "Tekst z PDF-a"

    monkeypatch.setattr(
        cv_pdf_preview, "docx_to_pdf", lambda _data, **_k: b"%PDF-1.7 wynik"
    )
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", _read_pdf)
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) == "Tekst z PDF-a"
    assert seen["pdf"] == b"%PDF-1.7 wynik"


@pytest.mark.parametrize(
    "content",
    [
        b"<html><body>CV</body></html>",
        b"{\\rtf1\\ansi CV}",
        b'<?xml version="1.0"?><office:document/>',
    ],
)
def test_word_worker_converts_only_real_word_files(monkeypatch, tmp_path, content):
    """Format wybiera LibreOffice po treści, więc plik pod nazwą `.doc` wybierałby filtr."""
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _no_conversion(*_a, **_k):
        raise AssertionError("to nie jest Word")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _no_conversion)
    path = tmp_path / "cv.doc"
    path.write_bytes(content)
    assert cte._worker_word(str(path)) is None


def test_word_worker_forces_the_import_filter_from_the_bytes(monkeypatch, tmp_path):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    seen: dict[str, str] = {}

    def _convert(_data, *, infilter):
        seen["infilter"] = infilter
        return b"%PDF-1.7"

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _convert)
    monkeypatch.setattr(cte, "_extract_pdf_inprocess", lambda _p: "Tekst")
    path = tmp_path / "cv.docx"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) == "Tekst"
    assert seen["infilter"] == "MS Word 97"


def test_word_worker_returns_none_when_conversion_fails(monkeypatch, tmp_path):
    from app.services import cv_pdf_preview, cv_text_extractor as cte

    def _unavailable(_data, **_k):
        raise cv_pdf_preview.PdfPreviewUnavailable("exit 1")

    monkeypatch.setattr(cv_pdf_preview, "docx_to_pdf", _unavailable)
    path = tmp_path / "cv.doc"
    path.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")
    assert cte._worker_word(str(path)) is None


def test_from_cv_logs_the_shape_of_a_file_it_could_not_read(
    monkeypatch, tmp_path, caplog
):
    """Bez nazwy pliku w logu: format i rozmiar wystarczą do następnego dochodzenia."""
    import asyncio
    import logging

    from fastapi import HTTPException

    from app.api import candidates
    from app.services import cv_text_extractor as cte

    monkeypatch.setattr(candidates.settings, "UPLOAD_DIR", str(tmp_path))
    monkeypatch.setattr(cte, "extract_text", lambda _path, _name: "")
    content = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1 binarny Word"
    with caplog.at_level(logging.WARNING, logger=candidates.logger.name):
        with pytest.raises(HTTPException) as refused:
            asyncio.run(
                candidates._extract_uploaded_cv_text(
                    content,
                    safe_name="Jan_Kowalski.doc",
                    client_filename="Jan_Kowalski.doc",
                )
            )
    assert refused.value.status_code == 400
    assert f"{len(content)} B" in caplog.text and ".doc" in caplog.text
    assert "Kowalski" not in caplog.text
