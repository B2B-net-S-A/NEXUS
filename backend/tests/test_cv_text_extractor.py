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

    monkeypatch.setattr(
        cte, "_extract_docx", lambda _p: "Jan Kowalski\nLead Engineer"
    )
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
