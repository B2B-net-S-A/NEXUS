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
