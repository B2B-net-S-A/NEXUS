"""Extract raw text from PDF/DOCX CV files for Claude analysis.

Ports `extractTextFromFile()` from `lib/cv-shared.ts`:
  - PDF: external `pdftotext` first, fall back to `pdfplumber` if not installed.
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
            text = _extract_pdf_pdfplumber(data)
    elif ext in (".docx", ".doc"):
        text = _extract_docx(data)
    else:
        raise CVTextExtractionError(f"Unsupported CV format: {ext}")

    if not text or not text.strip():
        raise CVTextExtractionError(f"Empty text extracted from {file_name}")

    return text
