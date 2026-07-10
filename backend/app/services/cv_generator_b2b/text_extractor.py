"""Extract raw text from PDF/DOCX CV files for Claude analysis.

Ports `extractTextFromFile()` from `lib/cv-shared.ts`:
  - PDF: external `pdftotext` first, fall back to `pdfplumber` if not installed;
    scanned / image-only PDFs (no text layer) go through a tesseract OCR
    fallback — the same pipeline `app.services.cv_text_extractor` uses for
    candidate uploads.
  - DOCX/DOC: `python-docx` (paragraphs + tables) — matches `mammoth.extractRawText` semantics.
"""

from __future__ import annotations

import io
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


class CVTextExtractionError(RuntimeError):
    """Raised when CV text extraction fails or format is unsupported."""


def _extract_pdf_pdftotext(data: bytes) -> str | None:
    """Use the `pdftotext` binary if available. Returns None if missing."""
    if not shutil.which("pdftotext"):
        return None

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=True) as f:
        f.write(data)
        f.flush()
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", f.name, "-"],
                capture_output=True,
                timeout=30,
                check=True,
            )
            return result.stdout.decode("utf-8", errors="replace")
        except subprocess.CalledProcessError as err:
            logger.warning("[cv_b2b] pdftotext failed (%s); falling back", err)
            return None


def _extract_pdf_pdfplumber(data: bytes) -> str:
    """Pure-Python fallback for PDF extraction."""
    import pdfplumber

    text_parts: list[str] = []
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            text_parts.append(page_text)
    return "\n".join(text_parts)


# Native extraction below this many characters means the PDF is most likely a
# scan / image-only export — retry via OCR (same threshold as
# app.services.cv_text_extractor; real CV text starts at >1KB).
_OCR_FALLBACK_THRESHOLD_CHARS = 100


def _extract_pdf_ocr(data: bytes) -> str | None:
    """Render PDF pages to images and OCR them via tesseract.

    Fallback for scanned / image-only PDFs where neither pdftotext nor
    pdfplumber find a text layer. Heavy (~2-5s per page) — capped to the
    first 10 pages; CVs are short. Returns None when OCR is unavailable.
    """
    try:
        import pytesseract  # type: ignore[import-untyped]
        from pdf2image import convert_from_bytes  # type: ignore[import-untyped]

        pages = convert_from_bytes(data, dpi=200, last_page=10)
        out: list[str] = []
        for img in pages:
            txt = pytesseract.image_to_string(img, lang="pol+eng")
            if txt:
                out.append(txt)
        return "\n\n".join(out) if out else ""
    except Exception as err:  # pragma: no cover — system tesseract may be missing
        logger.warning("[cv_b2b] OCR fallback failed: %s", err)
        return None


def _extract_docx(data: bytes) -> str:
    """Pull paragraphs and table cells from a DOCX."""
    from docx import Document

    doc = Document(io.BytesIO(data))
    parts: list[str] = []
    for para in doc.paragraphs:
        if para.text:
            parts.append(para.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text:
                    parts.append(cell.text)
    return "\n".join(parts)


def extract_text_from_file(data: bytes, file_name: str) -> str:
    """Extract plain text from a CV file (PDF/DOCX/DOC).

    Args:
        data: raw file bytes.
        file_name: original filename — only the extension is consulted.

    Returns:
        Extracted text (whitespace preserved, no normalization).

    Raises:
        CVTextExtractionError: on unsupported extension or empty extraction.
    """
    ext = Path(file_name).suffix.lower()

    if ext == ".pdf":
        text = _extract_pdf_pdftotext(data)
        if text is None or not text.strip():
            try:
                text = _extract_pdf_pdfplumber(data)
            except Exception as err:  # corrupt-ish PDF — OCR may still read it
                logger.warning(
                    "[cv_b2b] pdfplumber failed on %s: %s — trying OCR",
                    file_name,
                    err,
                )
                text = ""
        # Scanned / image-only PDFs yield (near-)empty text from both native
        # extractors — OCR is the only way to read them.
        if len((text or "").strip()) < _OCR_FALLBACK_THRESHOLD_CHARS:
            ocr = _extract_pdf_ocr(data)
            if ocr and len(ocr.strip()) > len((text or "").strip()):
                logger.info(
                    "[cv_b2b] %s: native PDF extraction near-empty, using OCR",
                    file_name,
                )
                text = ocr
    elif ext in (".docx", ".doc"):
        text = _extract_docx(data)
    else:
        raise CVTextExtractionError(f"Unsupported CV format: {ext}")

    if not text or not text.strip():
        raise CVTextExtractionError(
            f"Empty text extracted from {file_name} — plik wygląda na skan bez "
            "czytelnej warstwy tekstowej (OCR też nie odczytał tekstu). "
            "Spróbuj wgrać tekstową wersję PDF lub DOCX."
        )

    return text
