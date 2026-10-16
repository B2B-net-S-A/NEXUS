"""Numery egzemplarzy: jedna postać w bazie, żeby unikalność coś znaczyła.

„Wolny” zestaw szukało się dotąd w kilku zakładkach, a ten sam numer bywał
zapisany na trzy sposoby. W bazie trzymamy postać kanoniczną:

* numer ewidencyjny, S/N, numer karty — bez spacji na brzegach, WIELKIE litery,
* IMEI — same cyfry (14–16), ICCID — same cyfry (18–22),
* numer telefonu SIM — 9 cyfr (prefiks +48 zdejmowany).

Zła postać = ``IdentifierError`` z polskim zdaniem dla recepcji (422).
"""

from __future__ import annotations

import re
from typing import Optional

CATEGORY_LABELS: dict[str, str] = {
    "laptop": "Laptop",
    "telefon": "Telefon",
    "monitor": "Monitor",
    "karta_sim": "Karta SIM",
    "karta_dostepu": "Karta dostępu",
    "akcesorium": "Akcesorium",
    "inne": "Inne",
}

STATUS_LABELS: dict[str, str] = {
    "na_stanie": "Na stanie",
    "wydany": "Wydany",
    "serwis": "W serwisie",
    "wycofany": "Wycofany",
    "zgubiony": "Zgubiony",
}

CONDITION_LABELS: dict[str, str] = {
    "sprawny": "sprawny",
    "uszkodzony": "uszkodzony",
    "niekompletny": "niekompletny",
    "zgubiony": "zgubiony (brak zwrotu)",
}

FIELD_LABELS: dict[str, str] = {
    "inventory_number": "numer ewidencyjny",
    "serial_number": "numer seryjny",
    "imei": "IMEI",
    "iccid": "ICCID",
    "phone_number": "numer telefonu",
    "access_card_number": "numer karty",
}


class IdentifierError(ValueError):
    pass


def _blank(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = " ".join(str(value).split())
    return text or None


def code(value: Optional[str]) -> Optional[str]:
    """Numer ewidencyjny, S/N, numer karty: bez spacji na brzegach, wielkie litery."""
    text = _blank(value)
    return text.upper() if text else None


def imei(value: Optional[str]) -> Optional[str]:
    text = _blank(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if not 14 <= len(digits) <= 16:
        raise IdentifierError("IMEI ma 15 cyfr.")
    return digits


def iccid(value: Optional[str]) -> Optional[str]:
    text = _blank(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if not 18 <= len(digits) <= 22:
        raise IdentifierError("ICCID karty SIM ma 19–20 cyfr.")
    return digits


def phone(value: Optional[str]) -> Optional[str]:
    text = _blank(value)
    if text is None:
        return None
    digits = re.sub(r"\D", "", text)
    if len(digits) == 11 and digits.startswith("48"):
        digits = digits[2:]
    if len(digits) != 9:
        raise IdentifierError("Numer telefonu karty SIM ma 9 cyfr.")
    return digits


def phone_display(digits: Optional[str]) -> Optional[str]:
    """„500000077” → „+48 500 000 077” (jak w protokole recepcji)."""
    if not digits:
        return None
    return f"+48 {digits[:3]} {digits[3:6]} {digits[6:]}"


NORMALIZERS = {
    "inventory_number": code,
    "serial_number": code,
    "imei": imei,
    "iccid": iccid,
    "phone_number": phone,
    "access_card_number": code,
}


def normalize_identifiers(values: dict[str, Optional[str]]) -> dict[str, Optional[str]]:
    """Postać kanoniczna wszystkich numerów z ``values`` (tylko podane klucze)."""
    out: dict[str, Optional[str]] = {}
    for field, raw in values.items():
        normalizer = NORMALIZERS.get(field)
        out[field] = normalizer(raw) if normalizer else raw
    return out
