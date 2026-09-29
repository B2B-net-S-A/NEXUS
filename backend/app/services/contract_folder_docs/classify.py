"""Typ dokumentu kontraktu z NAZWY pliku (ticket 9, 29.09.2026).

Reguły z ticketu — pierwsza pasująca wygrywa; aneks, wypowiedzenie
i porozumienie sprawdzamy przed formatem numeru umowy (patrz niżej). Nazwę porównujemy
po złożeniu polskich znaków i wielkości liter („Porozumienie_rozwiązanie” =
„porozumienie rozwiazanie”). Słowa krótkie (NDA, OC, ZUS) muszą stać jako
osobne słowo — „OC” w środku „ocena” nie jest polisą.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from app.models.contract_document import ContractDocumentType

# Import bierze wyłącznie PDF i JPG (ticket: „Pomijaj pliki Word”).
IMPORTABLE_EXTENSIONS = frozenset({".pdf", ".jpg", ".jpeg"})

CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
}

# „1401-2026 B2B 04.05.2026”, „1401_2026_B2B_4.5.2026”, „1401/2026 B2B 04-05-2026”.
_CONTRACT_RE = re.compile(
    r"^\s*\d{1,5}\s*[-_/.]\s*\d{4}[\s_\-]*b2b[\s_\-]*\d{1,2}\s*[.\-_]\s*\d{1,2}\s*[.\-_]\s*\d{4}"
)
_WORD_SPLIT_RE = re.compile(r"[^0-9a-z]+")


@dataclass(frozen=True)
class Classified:
    doc_type: ContractDocumentType
    # Uwaga do raportu, gdy reguła zadziałała „na styk” (np. słowo „umowa”
    # bez formatu numeru → Inne). None = nic do sprawdzania.
    note: str | None = None


def fold(text: str) -> str:
    """Małe litery bez polskich znaków (ł → l ręcznie — NFKD go nie rozkłada)."""
    lowered = (text or "").casefold().replace("ł", "l")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def extension(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    if "." not in name:
        return ""
    return "." + name.rsplit(".", 1)[-1].casefold()


def stem(filename: str) -> str:
    name = (filename or "").rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[0] if "." in name else name


def is_importable(filename: str) -> bool:
    return extension(filename) in IMPORTABLE_EXTENSIONS


def classify_filename(filename: str) -> Classified:
    base = fold(stem(filename))
    words = {w for w in _WORD_SPLIT_RE.split(base) if w}

    # Słowa kluczowe PRZED formatem umowy: „1401-2026 B2B 04.05.2026 aneks 1”
    # zaczyna się numerem umowy, a jest aneksem.
    if "aneks" in base:
        return Classified(ContractDocumentType.annex)
    if "wypowiedzeni" in base:
        return Classified(ContractDocumentType.termination_notice)
    if "porozumieni" in base or "rozwiazani" in base:
        return Classified(ContractDocumentType.termination_agreement)
    if _CONTRACT_RE.match(base):
        return Classified(ContractDocumentType.contract)
    if "nda" in words:
        return Classified(ContractDocumentType.nda)
    if "polisa" in base or "oc" in words:
        return Classified(ContractDocumentType.oc_policy)
    if "zus" in words:
        return Classified(ContractDocumentType.zus_certificate)
    if "umowa" in base or "b2b" in words:
        return Classified(
            ContractDocumentType.other,
            note="Nazwa wygląda na umowę, ale nie ma formatu „numer B2B data” — zapisano jako Inne.",
        )
    return Classified(ContractDocumentType.other)
