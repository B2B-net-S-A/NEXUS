"""Nazwa pobieranego pliku umowy B2B (prośba Sandry i Klaudii, 26.10.2026).

„Umowa B2B 1555-2026 Kowalski Jan.pdf” — numer umowy, potem nazwisko i imię
osoby z umowy. Bez polskich znaków (decyzja Artura 26.10.2026), bo nazwa
idzie w nagłówku ``Content-Disposition`` i w załącznikach poczty. Ta sama
nazwa dla DOCX z Generatora, PDF-a do podpisu i podpisanej umowy.
"""

from __future__ import annotations

import re
import unicodedata

# NFKD nie rozkłada „ł” — bez zamiany „Łukasz” tracił pierwszą literę.
_NOT_DECOMPOSED = str.maketrans({"ł": "l", "Ł": "L"})


def _ascii_words(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text.translate(_NOT_DECOMPOSED))
    plain = plain.encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^A-Za-z0-9-]+", " ", plain).split())


def _surname_first(person_name: str) -> str:
    """Imię i nazwisko leżą w jednym polu — nazwisko to ostatnie słowo."""
    words = person_name.split()
    return " ".join(words[-1:] + words[:-1])


def contract_file_name(
    contract_number: str | None,
    person_name: str | None,
    *,
    ext: str,
    suffix: str = "",
) -> str:
    number = re.sub(r"\s*/\s*", "-", (contract_number or "").strip())
    parts = [
        "Umowa B2B",
        _ascii_words(number),
        _ascii_words(_surname_first(person_name or "")),
        _ascii_words(suffix),
    ]
    return f"{' '.join(p for p in parts if p)}.{ext}"


def mandate_file_name(
    signing_date: str | None, person_name: str | None, *, ext: str
) -> str:
    """„Umowa zlecenia 27-10-2026 Kowalski Jan.docx” — zlecenie nie ma numeru,
    identyfikuje je data zawarcia."""
    parts = [
        "Umowa zlecenia",
        _ascii_words((signing_date or "").replace(".", "-")),
        _ascii_words(_surname_first(person_name or "")),
    ]
    return f"{' '.join(p for p in parts if p)}.{ext}"
