"""Tekst dokumentu zamówienia + metadane, których odczyt CV nie potrzebuje.

Cienki wrapper na ``cv_text_extractor.extract_text`` (nietknięty — dzieli go
parser CV). Dokłada dwie rzeczy, bez których bramka automatu nie umie
stwierdzić, że dokument jest KOMPLETNY:

* **re-ekstrakcja przy literowaniu spacjami.** Dokument KIR-u pdfplumber oddaje
  jako „Z a tru d n ie n ie k o n tra k to ra" (75% tokenów jednoznakowych),
  a pdfminer.six — poprawnie. Produkcja wysyłała TAKI tekst do modelu; regexy
  polityk są wobec niego bezradne. Gdy udział tokenów jednoznakowych przekracza
  próg, tekst jest brany ponownie z pdfminera (już zależność projektu, już
  fallback tego samego ekstraktora — tylko dotąd używany wyłącznie po wyjątku).
* **metadane kompletności**: liczba stron, czy poszedł OCR (cap 10 stron —
  skan tabeli 30 osób uciąłby listę PO CICHU, produkując poprawnie wyglądające
  zamówienie dla pierwszych kilkunastu), czy tekst został poprawiony.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Optional

from app.services.cv_text_extractor import (
    _OCR_FALLBACK_THRESHOLD_CHARS,
    _extract_pdf_native,
    extract_text,
)

logger = logging.getLogger(__name__)

#: Powyżej tego udziału tokenów jednoznakowych tekst uznajemy za literowany
#: spacjami. Korpus 09.2026: KIR 0.75, wszystkie inne dokumenty ≤ 0.13.
LETTER_SPACING_RATIO_THRESHOLD = 0.30
#: Lustro capu z ``cv_text_extractor._extract_pdf_ocr`` (``last_page=10``).
OCR_PAGE_CAP = 10


@dataclass(frozen=True)
class OrderDocumentText:
    text: str
    page_count: Optional[int]
    #: OCR zadziałał (tekst natywny był krótszy niż próg) — heurystyka
    #: równoważna tej w ``_extract_pdf``.
    ocr_used: bool
    #: OCR zadziałał na dokumencie dłuższym niż cap → tekst NIE obejmuje
    #: wszystkich stron. Bramka automatu ma to traktować jak obcięcie.
    ocr_capped: bool
    #: Tekst został wzięty ponownie innym ekstraktorem (literowanie spacjami).
    reextracted_with: Optional[str]
    letter_spacing_ratio: float


def single_char_token_ratio(text: str) -> float:
    tokens = (text or "").split()
    if not tokens:
        return 0.0
    return sum(1 for t in tokens if len(t) == 1) / len(tokens)


def _pdf_page_count(path: str) -> Optional[int]:
    try:
        import pdfplumber  # type: ignore[import-untyped]

        with pdfplumber.open(path) as pdf:
            return len(pdf.pages)
    except Exception:  # noqa: BLE001 — metadane są best-effort
        return None


def _pdfminer_text(path: str) -> Optional[str]:
    try:
        from pdfminer.high_level import extract_text as _pdfminer_extract

        return _pdfminer_extract(path) or None
    except Exception as exc:  # noqa: BLE001
        logger.info(
            "[order_document_text] pdfminer re-extraction failed on %s: %s", path, exc
        )
        return None


def extract_order_text(path: str, filename: str) -> OrderDocumentText:
    """Tekst zamówienia + metadane. Nie rzuca na treści; rzuca jak ``extract_text``."""
    text = extract_text(path, filename)
    is_pdf = os.path.splitext(filename or "")[1].lower() == ".pdf"
    ratio = single_char_token_ratio(text)
    reextracted: Optional[str] = None
    if is_pdf and ratio > LETTER_SPACING_RATIO_THRESHOLD:
        alt = _pdfminer_text(path)
        if alt and single_char_token_ratio(alt) < ratio:
            logger.info(
                "[order_document_text] letter-spaced text (ratio %.2f) on %s — using pdfminer",
                ratio,
                filename,
            )
            text = alt
            reextracted = "pdfminer"
            ratio = single_char_token_ratio(alt)

    page_count = _pdf_page_count(path) if is_pdf else None
    ocr_used = False
    if is_pdf:
        native = _extract_pdf_native(path)
        ocr_used = not native or len(native.strip()) < _OCR_FALLBACK_THRESHOLD_CHARS
    ocr_capped = bool(ocr_used and page_count and page_count > OCR_PAGE_CAP)
    return OrderDocumentText(
        text=text,
        page_count=page_count,
        ocr_used=ocr_used,
        ocr_capped=ocr_capped,
        reextracted_with=reextracted,
        letter_spacing_ratio=round(ratio, 3),
    )
