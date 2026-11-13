"""Identyfikator kontrahenta: typ (NIP, PESEL, VAT UE, inny) i wartość po normalizacji.

Ta sama firma ma w kartotece jeden klucz niezależnie od zapisu w pliku:
„PL 526-030-05-17”, „5260300517” i VAT UE „PL5260300517” to ten sam NIP.
Polski NIP i PESEL muszą przejść sumę kontrolną — numer z literówką
przypiąłby faktury obcej firmy do konta Symfonii z kartoteki.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Optional

from app.services.finance_ledger_schema import ID_VALUE_MAX
from app.services.order_client_identity import nip_checksum_valid

_EU_PREFIXES = frozenset(
    "AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PT RO SE SI SK XI".split()
)
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
_SEPARATORS = re.compile(r"[\s.\-/]")
_VAT_EU = re.compile(r"([A-Z]{2})([A-Z0-9+*]{2,})")

#: Słowa z kolumny „Typ identyfikatora” (po zdjęciu znaków i spacji).
_TYPE_WORDS = {
    "nip": "nip",
    "nippl": "nip",
    "pesel": "pesel",
    "vatue": "vat_eu",
    "nipue": "vat_eu",
    "ue": "vat_eu",
    "vat": "vat_eu",
    "euvat": "vat_eu",
    "inny": "other",
    "inne": "other",
    "other": "other",
    "zagraniczny": "other",
    "brak": "other",
}

TYPE_LABELS = {"nip": "NIP", "pesel": "PESEL", "vat_eu": "VAT UE", "other": "inny"}


class IdentifierError(ValueError):
    """Zdanie po polsku do podglądu importu albo formularza."""


@dataclass(frozen=True)
class Identifier:
    type: str
    value: str


def fold(text: str) -> str:
    """Małe litery bez polskich znaków i bez niczego poza literami i cyframi."""

    decomposed = (
        unicodedata.normalize("NFKD", text or "").replace("ł", "l").replace("Ł", "L")
    )
    plain = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9]", "", plain.lower())


def pesel_checksum_valid(digits: str) -> bool:
    if len(digits) != 11 or not digits.isdigit():
        return False
    total = sum(int(d) * w for d, w in zip(digits[:10], _PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(digits[10])


def id_type_from_text(raw: Optional[str]) -> Optional[str]:
    """„NIP”, „VAT UE”, „Inny” → typ; puste albo nieznane słowo = ``None``."""

    word = fold(raw or "")
    return _TYPE_WORDS.get(word) if word else None


def _compact(raw: str) -> str:
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", raw or "").upper())


def normalize_search(raw: str) -> str:
    """Fraza wyszukiwania w postaci identyfikatora: „PL 526-030” → „526030”."""

    value = _compact(raw)
    if value.startswith("PL") and value[2:].isdigit():
        value = value[2:]
    return value if any(ch.isdigit() for ch in value) else ""


def _nip(value: str) -> Identifier:
    digits = value[2:] if value.startswith("PL") else value
    if not (len(digits) == 10 and digits.isdigit()):
        raise IdentifierError("NIP ma 10 cyfr.")
    if not nip_checksum_valid(digits):
        raise IdentifierError("NIP ma niepoprawną sumę kontrolną.")
    return Identifier("nip", digits)


def _pesel(value: str) -> Identifier:
    if not pesel_checksum_valid(value):
        raise IdentifierError("PESEL ma 11 cyfr z poprawną sumą kontrolną.")
    return Identifier("pesel", value)


def _vat_eu(value: str) -> Identifier:
    match = _VAT_EU.fullmatch(value)
    if match is None or match.group(1) not in (_EU_PREFIXES | {"PL"}):
        raise IdentifierError("VAT UE zaczyna się od kodu kraju, np. DE123456789.")
    if match.group(1) == "PL":
        return _nip(value)
    return Identifier("vat_eu", value)


def normalize(
    raw_value: Optional[str], raw_type: Optional[str] = None
) -> Optional[Identifier]:
    """Identyfikator z pliku albo formularza; pusta wartość = ``None``.

    Bez typu zgadujemy: 10 cyfr = NIP (zła suma to błąd, nie „inny”), 11 cyfr
    z poprawną sumą = PESEL, prefiks kraju UE = VAT UE, reszta = inny.
    """

    value = _compact(raw_value or "")
    if not value:
        return None
    if len(value) > ID_VALUE_MAX:
        raise IdentifierError(f"Identyfikator ma najwyżej {ID_VALUE_MAX} znaków.")
    kind = id_type_from_text(raw_type) if raw_type else None
    if raw_type and fold(raw_type) and kind is None:
        raise IdentifierError(f"Nieznany typ identyfikatora: {raw_type.strip()[:40]}.")
    if kind == "nip":
        return _nip(value)
    if kind == "pesel":
        return _pesel(value)
    if kind == "vat_eu":
        return _vat_eu(value)
    if kind == "other":
        return Identifier("other", value)
    if value.isdigit() and len(value) == 10:
        return _nip(value)
    if value.startswith("PL") and value[2:].isdigit() and len(value) == 12:
        return _nip(value)
    if value.isdigit() and len(value) == 11 and pesel_checksum_valid(value):
        return Identifier("pesel", value)
    match = _VAT_EU.fullmatch(value)
    if match and match.group(1) in _EU_PREFIXES:
        return Identifier("vat_eu", value)
    return Identifier("other", value)
