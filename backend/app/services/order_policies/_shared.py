"""Wspólne klocki polityk klientowych: etykieta → wartość, okres, wiersze.

Wszystko DETERMINISTYCZNE i oparte na ETYKIETACH z dokumentu, nie na
kolejności liczb w tekście — to jest to, czemu bramka automatu ufa
(proweniencja deterministyczna). Model wybiera interpretację; polityka
stosuje regułę.
"""

from __future__ import annotations

import re
import unicodedata
from decimal import Decimal
from typing import Optional

from app.services.order_pdf_parser import (
    ConsultantOrderRow,
    OrderExtraction,
    _labelled_amount,
    _normalize_amount,
    _normalize_date,
)

__all__ = [
    "ConsultantOrderRow",
    "OrderExtraction",
    "clean_person_name",
    "clear_field",
    "date_range_first",
    "fold",
    "labelled_amount",
    "labelled_date",
    "labelled_text",
    "normalize_amount",
    "normalize_date",
    "set_field",
]

labelled_amount = _labelled_amount
normalize_amount = _normalize_amount
normalize_date = _normalize_date

_DATE = r"(\d{4}-\d{1,2}-\d{1,2}|\d{1,2}[./-]\d{1,2}[./-]\d{4})"
_RANGE_SEP = r"\s*(?:[-–—]|do|to)\s*"
# Znaki sterujące kierunkiem tekstu (LRE/RLE/PDF, ZWSP…) — ekstrakcja z PDF
# potrafi wstawić je przed nazwiskiem (mLeasing: „BL(mL) - ‪‪‪Urszula Pasik").
_INVISIBLE_RE = re.compile(r"[​-‏‪-‮⁠-⁤﻿]")
# Tytuły grzecznościowe przed nazwiskiem w prozie („P. Konrad Niemyjski").
_HONORIFIC_RE = re.compile(r"^(?:p\.|pan|pani|mr\.?|mrs\.?|ms\.?)\s+", re.IGNORECASE)


def fold(text: str) -> str:
    """Casefold + bez diakrytyków (OCR gubi ogonki)."""
    folded = unicodedata.normalize("NFKD", (text or "").casefold()).replace("ł", "l")
    return "".join(ch for ch in folded if not unicodedata.combining(ch))


def labelled_text(
    label: str,
    text: str,
    *,
    value: str = r"[A-Z0-9][A-Z0-9._/\-]*",
    require_digit: bool = True,
) -> Optional[str]:
    """Pierwsza wartość ZA etykietą (regex), która niesie cyfrę.

    Guard na cyfrę łapie puste pole, po którym ``\\s*`` przeskoczyłoby do
    początku kolejnej etykiety. Etykieta bywa powtórzona (nagłówek/stopka) —
    iterujemy po wystąpieniach aż do sensownej wartości.
    """
    pattern = re.compile(label + r"\s*[:#\-–—]?\s*(" + value + r")", re.IGNORECASE)
    for m in pattern.finditer(text or ""):
        candidate = m.group(1).strip().rstrip(".,;")
        if candidate and (not require_digit or any(ch.isdigit() for ch in candidate)):
            return candidate
    return None


def labelled_date(label: str, text: str, *, end: bool = False) -> Optional[str]:
    """Pierwsza data (ISO albo dd.mm.rrrr) stojąca za etykietą; ISO w wyniku."""
    pattern = re.compile(label + r"[^\d\n]{0,40}?" + _DATE, re.IGNORECASE | re.DOTALL)
    for m in pattern.finditer(text or ""):
        iso = _normalize_date(m.group(1), end=end)
        if iso:
            return iso
    return None


def date_range_first(
    text: str, *, after_label: Optional[str] = None
) -> tuple[Optional[str], Optional[str]]:
    """Pierwszy zakres „DATA – DATA" / „od DATA do DATA" (opcjonalnie za etykietą)."""
    prefix = (after_label + r"[^\d\n]{0,60}?") if after_label else r"(?:od\s+)?"
    pattern = re.compile(prefix + _DATE + _RANGE_SEP + _DATE, re.IGNORECASE | re.DOTALL)
    m = pattern.search(text or "")
    if not m:
        return None, None
    return _normalize_date(m.group(1), end=False), _normalize_date(m.group(2), end=True)


def clean_person_name(raw: str) -> str:
    """Zbij białe znaki, zdejmij znaki niewidoczne i tytuł grzecznościowy."""
    value = _INVISIBLE_RE.sub("", raw or "")
    value = re.sub(r"\s+", " ", value).strip(" ,;:-–—")
    return _HONORIFIC_RE.sub("", value).strip()


def set_field(
    result: OrderExtraction, name: str, value: object, *, confidence: float = 1.0
) -> None:
    """Ustaw pole z proweniencją deterministyczną (confidence 1.0 = etykieta)."""
    setattr(result, name, value)
    result.confidence[name] = confidence


def clear_field(result: OrderExtraction, name: str) -> None:
    setattr(result, name, None)
    result.confidence.pop(name, None)


def money_after(label: str, text: str) -> Optional[Decimal]:
    """Kwota za etykietą — alias czytelniejszy niż prywatny helper parsera."""
    return _labelled_amount(label, text)
