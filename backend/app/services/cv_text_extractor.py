"""CV text extractor — PDF / DOCX / TXT → plain text.

The upload pipeline stores the original file on disk but never populated
`raw_cv_text`, which left the enrichment LLM without any input. This module
closes the gap.

Design
------
Dispatch by the file's real format (first bytes), falling back to the extension
(case-insensitive). Heavy libraries imported lazily so
import-time cost stays near zero in environments where CV uploads never happen
(e.g. CI unit tests that don't touch candidates).

Failures are swallowed into an empty string so the calling pipeline can proceed
with `raw_cv_text=""` and degrade gracefully to regex parsing. Only an
explicitly unsupported extension raises `UnsupportedCvFormat`; the upload
endpoint catches that and logs, still accepting the file.

Usage
-----
>>> from app.services.cv_text_extractor import extract_text
>>> text = await asyncio.to_thread(extract_text, "/tmp/nexus/uploads/file.pdf", "file.pdf")
"""

from __future__ import annotations

import logging
import os
import re
from typing import Optional

from app.core.log_safety import safe_filename

logger = logging.getLogger(__name__)


class UnsupportedCvFormat(Exception):
    """Raised when the file extension is not supported for text extraction."""


# Triple-or-more blank lines → a single blank line. Keeps paragraph structure.
_MULTI_BLANK_LINE = re.compile(r"\n{3,}")
# Runs of horizontal whitespace (spaces, tabs) collapsed to a single space.
_HORIZONTAL_WS = re.compile(r"[ \t]+")
# Trailing whitespace at end of each line.
_LINE_TRAILING = re.compile(r"[ \t]+\n")


def _normalize(text: str) -> str:
    """Collapse whitespace while preserving paragraph breaks.

    Drops NUL bytes first: some PDFs (broken font maps, OCR layers) yield
    ``\x00`` in the extracted text and Postgres rejects it at insert
    (``invalid byte sequence for encoding "UTF8": 0x00``), so ``/from-cv``
    answered 500 instead of creating the candidate.
    """
    if not text:
        return ""
    text = text.replace("\x00", "")
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _LINE_TRAILING.sub("\n", text)
    text = _MULTI_BLANK_LINE.sub("\n\n", text)
    return text.strip()


# Threshold below which we suspect the PDF is a scan / image-only and fall
# back to OCR. 100 chars is enough to capture page-numbers/headers from a
# corrupt extraction; real CV text starts at >1KB.
_OCR_FALLBACK_THRESHOLD_CHARS = 100


# Średnia długość „słowa” (znaki / przerwy), powyżej której tekst uznajemy za
# SKLEJONY. Zwykłe CV ma ~6–8; PDF-y z ciasnym odstępem między literami dają
# w domyślnym odczycie 12–37 („ledtheqainitiativeandthedevelopment…”) —
# 1 581 CV na produkcji (23.09.2026), niewidocznych dla wyszukiwania słów.
GLUED_AVG_WORD_LEN = 12.0
_WHITESPACE_RUN = re.compile(r"\s+")


def avg_word_length(text: str) -> float:
    return len(text) / (len(_WHITESPACE_RUN.findall(text)) + 1)


def looks_glued(text: Optional[str]) -> bool:
    """Tekst bez przerw między słowami (krótkie teksty nie są oceniane)."""
    if not text or len(text) < 300:
        return False
    return avg_word_length(text) > GLUED_AVG_WORD_LEN


def _pdfplumber_text(pdf, **kwargs) -> str:
    return "\n\n".join(
        txt for page in pdf.pages if (txt := page.extract_text(**kwargs) or "")
    )


def _extract_pdf_native(path: str) -> Optional[str]:
    """Try pdfplumber first (better multi-column / layout), fall back to
    pdfminer.six on any failure. Both are pure-text extractors — return None
    if PDF is image-only (caller will trigger OCR).

    Sklejony wynik domyślnego odczytu (``looks_glued``) jest czytany drugi raz
    z ``x_tolerance=1``: pdfplumber wstawia spację, gdy odstęp między literami
    przekracza próg (domyślnie 3 pt), a PDF-y z ciasnym kerningiem mają odstęp
    międzywyrazowy poniżej niego. Próbka 24 takich CV z produkcji: średnia
    długość słowa 12–37 → 6–8. Próg niższy dla WSZYSTKICH PDF-ów ryzykowałby
    rozcinanie słów w rozstrzelonych nagłówkach, więc to tylko ścieżka zapasowa.
    """
    # pdfplumber preserves layout columns better than pdfminer for modern CVs.
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(path) as pdf:
            text = _pdfplumber_text(pdf)
            if looks_glued(text):
                tight = _pdfplumber_text(pdf, x_tolerance=1)
                if avg_word_length(tight) < avg_word_length(text):
                    text = tight
        if text:
            return text
    except Exception as e:  # pragma: no cover — defensive
        logger.info(
            "[cv_text_extractor] pdfplumber failed on %s: %s — trying pdfminer", path, e
        )

    # Legacy fallback for rare PDFs that pdfplumber chokes on.
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract

        return _pdfminer_extract(path) or ""
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[cv_text_extractor] pdfminer also failed on %s: %s", path, e)
        return None


def _extract_pdf_ocr(path: str) -> Optional[str]:
    """Render PDF pages to images and OCR them via tesseract.

    Used when native text extraction yields too little — typical for scanned
    CVs or image-only PDFs. Polish + English language packs cover most cases.
    Heavy: ~2-5s per page; we cap to first 10 pages (CVs are short).
    """
    try:
        import pytesseract  # type: ignore[import-untyped]
        from pdf2image import convert_from_path  # type: ignore[import-untyped]

        pages = convert_from_path(path, dpi=200, last_page=10)
        out: list[str] = []
        for img in pages:
            txt = pytesseract.image_to_string(img, lang="pol+eng")
            if txt:
                out.append(txt)
        return "\n\n".join(out) if out else ""
    except (
        Exception
    ) as e:  # pragma: no cover — defensive (system tesseract may be missing)
        logger.warning("[cv_text_extractor] OCR fallback failed on %s: %s", path, e)
        return None


def _extract_pdf(path: str) -> Optional[str]:
    """Extract PDF text — native first (pdfplumber→pdfminer), OCR fallback if
    output is suspiciously short (likely a scan).

    Returns None only on total failure so the dispatcher degrades to "".
    """
    native = _extract_pdf_native(path)
    if native and len(native.strip()) >= _OCR_FALLBACK_THRESHOLD_CHARS:
        return native
    # Either native extraction failed, or yielded near-empty output → OCR.
    ocr = _extract_pdf_ocr(path)
    if ocr and len(ocr.strip()) >= _OCR_FALLBACK_THRESHOLD_CHARS:
        logger.info(
            "[cv_text_extractor] PDF %s extracted via OCR (native too short)", path
        )
        return ocr
    # Return whichever has more content (could still be empty).
    return (native or "") if (len(native or "") >= len(ocr or "")) else (ocr or "")


def _extract_docx(path: str) -> Optional[str]:
    """Extract text from a DOCX (or legacy .doc, best-effort) via python-docx."""
    try:
        from docx import Document  # type: ignore[import-untyped]

        from app.core.zip_guard import assert_safe_ooxml

        assert_safe_ooxml(path)
        doc = Document(path)
        lines = [p.text for p in doc.paragraphs if p.text]
        # Include table cells — CVs often layout experience as tables.
        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    if cell.text:
                        lines.append(cell.text)
        return "\n".join(lines)
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[cv_text_extractor] python-docx failed on %s: %s", path, e)
        return None


def _extract_txt(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[cv_text_extractor] txt read failed on %s: %s", path, e)
        return None


def _declared_extension(file_path: str, filename: str) -> str:
    """Extension from the filename (stable across temp-file renames), falling
    back to the on-disk path."""
    _, ext = os.path.splitext(filename or "")
    if not ext:
        _, ext = os.path.splitext(file_path or "")
    return ext.lower()


_PDF_MAGIC = b"%PDF-"
_ZIP_MAGIC = b"PK\x03\x04"
_OLE_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
# PDF allows junk before the header; readers look within the first 1 KB.
_SNIFF_BYTES = 1024


def sniff_extension(file_path: str) -> Optional[str]:
    """Real format from the file's first bytes: ``.pdf``, ``.docx``, ``.doc``.

    The NAME lies. Measured on prod 2026-09-22: 3 320 Traffit CVs named
    ``*.docx`` are PDFs inside (Traffit serves its converted copy under the
    original name). Dispatching by name sent them to python-docx, which failed,
    and the backfill marked them ``empty`` — terminal — so their text was never
    searched. ``None`` = no known signature (plain text, images, garbage);
    the caller keeps the declared extension then.
    """
    try:
        with open(file_path, "rb") as f:
            head = f.read(_SNIFF_BYTES)
    except OSError:
        return None
    if head.startswith(_OLE_MAGIC):
        return ".doc"
    if head.startswith(_ZIP_MAGIC):
        try:
            import zipfile

            with zipfile.ZipFile(file_path) as zf:
                if "word/document.xml" in zf.namelist():
                    return ".docx"
        except Exception:  # noqa: BLE001 — broken zip = unknown format
            return None
        return None  # odt/xlsx/pages — a zip, but not a Word document
    if _PDF_MAGIC in head:
        return ".pdf"
    return None


def sniff_extension_bytes(data: bytes) -> Optional[str]:
    """``sniff_extension`` dla bajtów w pamięci (generator CV — runda 6 audytu).

    Generator CV dostaje plik jako bajty i do 26.09.2026 wybierał parser po
    nazwie: PDF zapisany jako ``.docx`` (3 320 takich z Traffita) kończył się
    „Nie można odczytać dokumentu DOCX.” Ta sama reguła co ``sniff_extension``.
    """
    head = bytes(data[:_SNIFF_BYTES]) if data else b""
    if head.startswith(_OLE_MAGIC):
        return ".doc"
    if head.startswith(_ZIP_MAGIC):
        try:
            import io
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                if "word/document.xml" in zf.namelist():
                    return ".docx"
        except Exception:  # noqa: BLE001 — broken zip = unknown format
            return None
        return None
    if _PDF_MAGIC in head:
        return ".pdf"
    return None


def _resolve_extension(file_path: str, filename: str) -> str:
    """Format to parse as: the sniffed one when the bytes say so, otherwise the
    declared extension."""
    declared = _declared_extension(file_path, filename)
    sniffed = sniff_extension(file_path)
    if sniffed and sniffed != declared:
        logger.info(
            "[cv_text_extractor] %s declared %r but content is %r — using content",
            # runda 6 audytu: nazwa pliku CV to zwykle imię i nazwisko
            safe_filename(filename or file_path),
            declared,
            sniffed,
        )
        return sniffed
    return declared


def extract_text(file_path: str, filename: str) -> str:
    """Read `file_path` and return its text content as a single string.

    Parameters
    ----------
    file_path : str
        Absolute or relative path to the file on disk.
    filename : str
        Original uploaded filename — used to determine format when `file_path`
        is an extension-less temp file.

    Returns
    -------
    str
        Extracted, whitespace-normalized text. Empty string on extraction
        failure (never None).

    Raises
    ------
    UnsupportedCvFormat
        If the format is not one of: .pdf, .docx, .doc, .txt. The format comes
        from the file's first bytes when they carry a known signature, so a PDF
        saved as ``cv.docx`` (or ``cv.odt``) is read as a PDF.
    """
    ext = _resolve_extension(file_path, filename)

    if ext == ".pdf":
        raw = _extract_pdf(file_path)
    elif ext in (".docx", ".doc"):
        raw = _extract_docx(file_path)
    elif ext == ".txt":
        raw = _extract_txt(file_path)
    else:
        raise UnsupportedCvFormat(
            f"Unsupported CV format: {ext!r} (filename={filename!r}). "
            "Supported: .pdf, .docx, .doc, .txt"
        )

    return _normalize(raw or "")
