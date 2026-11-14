"""PESEL w płacach (K7a): suma kontrolna, data urodzenia, płeć, maska, skrót.

Decyzja Artura z 13.11.2026: PESEL i dane do ZUS/PIT trzymamy w NEXUSIE
zaszyfrowane, tylko na potrzeby Kadr i Płac. Ten moduł nie loguje i nie
zwraca w komunikatach żadnej cyfry numeru — błąd mówi tylko, co jest nie tak.

Skrót (HMAC-SHA256, klucz wyprowadzony z ``M365_TOKEN_ENCRYPTION_KEY`` z osobnym
przeznaczeniem, jak skrót rachunku w ``billing_details.account_fingerprint``)
pilnuje, żeby dwie osoby nie miały tego samego PESEL-u, bez odszyfrowywania.
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import date
from typing import Optional

from app.core.config import settings
from app.core.encryption import TokenCipherNotConfigured
from app.services.hr.payroll_errors import PayrollError

WEIGHTS = (1, 3, 7, 9, 1, 3, 7, 9, 1, 3)
#: Przesunięcie miesiąca w PESEL-u → stulecie.
_CENTURIES = {0: 1900, 20: 2000, 40: 2100, 60: 2200, 80: 1800}
MASK = "•••••••"


class PeselError(PayrollError):
    """Zły PESEL — komunikat bez cyfr numeru."""


def checksum_ok(value: str) -> bool:
    if len(value) != 11 or not value.isdigit():
        return False
    total = sum(int(digit) * weight for digit, weight in zip(value, WEIGHTS))
    return (10 - total % 10) % 10 == int(value[10])


def birth_date(value: str) -> Optional[date]:
    """Data urodzenia zapisana w PESEL-u; ``None``, gdy nie ma takiej daty."""

    year = int(value[0:2])
    month = int(value[2:4])
    day = int(value[4:6])
    offset = (month // 20) * 20
    century = _CENTURIES.get(offset)
    if century is None:
        return None
    try:
        return date(century + year, month - offset, day)
    except ValueError:
        return None


def sex(value: str) -> str:
    """„F” dla parzystej dziesiątej cyfry, „M” dla nieparzystej."""

    return "F" if int(value[9]) % 2 == 0 else "M"


def clean(raw: Optional[str]) -> Optional[str]:
    """Tekst z formularza → 11 cyfr albo ``None``; zły numer = 422 bez cyfr w treści."""

    text = "".join(ch for ch in (raw or "") if not ch.isspace())
    if not text:
        return None
    if len(text) != 11 or not text.isdigit():
        raise PeselError("PESEL to 11 cyfr.")
    if not checksum_ok(text):
        raise PeselError("PESEL ma złą cyfrę kontrolną — sprawdź numer.")
    if birth_date(text) is None:
        raise PeselError("PESEL zawiera niemożliwą datę urodzenia — sprawdź numer.")
    return text


def last4(value: str) -> str:
    return value[-4:]


def masked(last_digits: Optional[str]) -> Optional[str]:
    """Na ekranie: kropki i 4 ostatnie cyfry."""

    return f"{MASK}{last_digits}" if last_digits else None


def fingerprint(value: str) -> str:
    secret = settings.M365_TOKEN_ENCRYPTION_KEY
    if not secret:
        raise TokenCipherNotConfigured("brak klucza szyfrowania danych płacowych")
    key = hashlib.sha256(b"nexus-payroll-pesel:" + secret.encode()).digest()
    return hmac.new(key, value.encode(), hashlib.sha256).hexdigest()


__all__ = [
    "MASK",
    "PeselError",
    "birth_date",
    "checksum_ok",
    "clean",
    "fingerprint",
    "last4",
    "masked",
    "sex",
]
