"""Czego NIE przenosimy z plików recepcji (decyzja D10) i jak to rozpoznać.

W plikach recepcji leżały pełne klucze odzyskiwania BitLocker, jawne kody PUK,
PESEL-e i prywatne e-maile. Rejestr nie ma na nie kolumn, a import odrzuca je
dwa razy: po nagłówku kolumny (cała kolumna nie jest czytana) i po wzorcu
wartości w kolumnach, które czytamy (wartość znika, wiersz dostaje powód).

Funkcje są czyste — test na fikcyjnych wierszach nie potrzebuje bazy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

#: Klucz odzyskiwania BitLocker: 8 grup po 6 cyfr (48 cyfr), zwykle z myślnikami.
_BITLOCKER = re.compile(r"(?<!\d)(?:\d{6}[\s-]?){7}\d{6}(?!\d)")
_DIGIT_RUN = re.compile(r"(?<![\d-])\d{8,11}(?![\d-])")
_EMAIL = re.compile(r"[\w.+-]+@([\w-]+(?:\.[\w-]+)+)", re.UNICODE)
_PESEL_WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)

#: Domeny skrzynek prywatnych — e-mail z nich nie trafia do NEXUSA.
PRIVATE_EMAIL_DOMAINS = frozenset(
    {
        "gmail.com",
        "googlemail.com",
        "wp.pl",
        "o2.pl",
        "onet.pl",
        "onet.eu",
        "op.pl",
        "interia.pl",
        "interia.eu",
        "poczta.fm",
        "tlen.pl",
        "gazeta.pl",
        "vp.pl",
        "yahoo.com",
        "yahoo.pl",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "icloud.com",
        "me.com",
        "proton.me",
        "protonmail.com",
        "aol.com",
        "gmx.com",
        "gmx.net",
    }
)

#: Fragmenty nagłówków kolumn z sekretami — takiej kolumny nie czytamy wcale.
SECRET_HEADER_HINTS: tuple[tuple[str, str], ...] = (
    ("bitlocker", "klucz BitLocker"),
    ("recovery", "klucz BitLocker"),
    ("odzyskiw", "klucz BitLocker"),
    ("klucz", "klucz BitLocker"),
    ("puk", "kod PUK"),
    ("pin", "kod PIN"),
    ("pesel", "PESEL"),
    ("hasło", "hasło"),
    ("haslo", "hasło"),
    ("password", "hasło"),
    ("prywatn", "prywatny e-mail"),
)


def fold(value: str) -> str:
    """Małe litery, bez ogonków i zbędnych spacji (porównania nagłówków i nazwisk)."""
    text = unicodedata.normalize("NFKD", value).replace("ł", "l").replace("Ł", "L")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    # „lnformacja” (małe L zamiast I) jest w nagłówku pliku recepcji.
    return " ".join(text.casefold().replace("lnformacja", "informacja").split())


def secret_header_reason(header: str) -> str | None:
    """Powód odrzucenia kolumny po nagłówku albo ``None``."""
    folded = fold(header)
    words = set(re.split(r"[^a-z0-9]+", folded))
    for hint, reason in SECRET_HEADER_HINTS:
        # „pin” tylko jako całe słowo (nie „shipping”, „spinacz”).
        if hint == "pin":
            if "pin" in words:
                return reason
            continue
        if hint in folded:
            return reason
    return None


def is_bitlocker_key(value: str) -> bool:
    return bool(_BITLOCKER.search(value))


def is_pesel(value: str) -> bool:
    """11 cyfr z poprawną cyfrą kontrolną (miesiąc z przesunięciem stulecia)."""
    if not re.fullmatch(r"\d{11}", value):
        return False
    month = int(value[2:4]) % 20
    if not 1 <= month <= 12 or not 1 <= int(value[4:6]) <= 31:
        return False
    total = sum(int(d) * w for d, w in zip(value[:10], _PESEL_WEIGHTS))
    return (10 - total % 10) % 10 == int(value[10])


def looks_like_puk(value: str) -> bool:
    """Kod PUK: dokładnie 8 cyfr."""
    return bool(re.fullmatch(r"\d{8}", value))


def email_domain(value: str) -> str | None:
    match = _EMAIL.search(value)
    return match.group(1).casefold() if match else None


def is_private_email(value: str) -> bool:
    domain = email_domain(value)
    return domain is not None and domain in PRIVATE_EMAIL_DOMAINS


@dataclass(frozen=True)
class Cleaned:
    value: str | None
    reasons: tuple[str, ...]


def clean_text(value: str, *, identifier: bool = False) -> Cleaned:
    """Wycina z wartości sekrety; ``identifier`` = kolumna numeru (bez wzorca PUK).

    Numery egzemplarzy bywają ośmiocyfrowe (karta dostępu), więc wzorzec PUK
    i PESEL-u stosujemy tylko do tekstu swobodnego (uwagi, posiadacz, stan).
    Klucz BitLocker i e-mail prywatny są odrzucane w każdej kolumnie.
    """
    reasons: list[str] = []
    text = value
    if is_bitlocker_key(text):
        text = _BITLOCKER.sub(" ", text)
        reasons.append("klucz BitLocker")
    for match in list(_EMAIL.finditer(text)):
        if match.group(1).casefold() in PRIVATE_EMAIL_DOMAINS:
            text = text.replace(match.group(0), " ")
            reasons.append("prywatny e-mail")
    if not identifier:
        for token in _DIGIT_RUN.findall(text):
            if is_pesel(token):
                text = text.replace(token, " ")
                reasons.append("PESEL")
            elif looks_like_puk(token):
                text = text.replace(token, " ")
                reasons.append("kod PUK")
    elif is_pesel(text.strip()):
        reasons.append("PESEL")
        text = ""
    cleaned = " ".join(text.split()) or None
    return Cleaned(cleaned, tuple(dict.fromkeys(reasons)))
