"""CV text extractor — PDF / DOCX / TXT → plain text.

The upload pipeline stores the original file on disk but never populated
`raw_cv_text`, which left the enrichment LLM without any input. This module
closes the gap.

Design
------
Dispatch by extension (case-insensitive). Heavy libraries imported lazily so
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
    """Collapse whitespace while preserving paragraph breaks."""
    if not text:
        return ""
    text = _HORIZONTAL_WS.sub(" ", text)
    text = _LINE_TRAILING.sub("\n", text)
    text = _MULTI_BLANK_LINE.sub("\n\n", text)
    return text.strip()


def _extract_pdf(path: str) -> Optional[str]:
    """Extract text from a PDF file via pdfminer.six.

    Returns None on any failure so the dispatcher can degrade to an empty
    string rather than raising into the upload response.
    """
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract

        return _pdfminer_extract(path) or ""
    except Exception as e:  # pragma: no cover — defensive
        logger.warning("[cv_text_extractor] pdfminer failed on %s: %s", path, e)
        return None


def _extract_docx(path: str) -> Optional[str]:
    """Extract text from a DOCX (or legacy .doc, best-effort) via python-docx."""
    try:
        from docx import Document  # type: ignore[import-untyped]

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


def _resolve_extension(file_path: str, filename: str) -> str:
    """Prefer the filename extension (stable across temp-file renames),
    falling back to the on-disk path."""
    _, ext = os.path.splitext(filename or "")
    if not ext:
        _, ext = os.path.splitext(file_path or "")
    return ext.lower()


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
        If the extension is not one of: .pdf, .docx, .doc, .txt.
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
