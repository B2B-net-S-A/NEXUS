"""PESEL w płacach (K7a): suma kontrolna, data urodzenia, płeć, maska, skrót.

Decyzja Artura z 13.11.2026: PESEL i dane do ZUS/PIT trzymamy w NEXUSIE
zaszyfrowane, tylko na potrzeby Kadr i Płac. Ten moduł nie loguje i nie
zwraca w komunikatach żadnej cyfry numeru — błąd mówi tylko, co jest nie tak.

Skrót (HMAC-SHA256, klucz wyprowadzony z ``M365_TOKEN_ENCRYPTION_KEY`` z osobnym
przeznaczeniem, jak skrót rachunku w ``billing_details.account_fingerprint``)
pilnuje, żeby dwie osoby nie miały tego samego PESEL-u, bez odszyfrowywania.
Zapis bieżącym kluczem, porównanie wszystkimi (``fingerprints``): skrót sprzed
rotacji klucza pasuje do poprzedniego, dopóki ``app.cli.token_cipher_rotate``
go nie przeliczy.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from app.core.encryption import get_token_cipher
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


def clean(raw: object) -> Optional[str]:
    """Tekst z formularza → 11 cyfr albo ``None``; zły numer = 422 bez cyfr w treści."""

    text = "".join(ch for ch in str(raw if raw is not None else "") if not ch.isspace())
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


#: Przeznaczenie klucza skrótu PESEL-u (``TokenCipher.fingerprints``).
FINGERPRINT_PURPOSE = b"nexus-payroll-pesel:"


def fingerprints(value: str) -> tuple[str, ...]:
    """Skróty PESEL-u każdym kluczem, bieżący pierwszy; brak klucza =
    ``TokenCipherNotConfigured``."""

    return get_token_cipher().fingerprints(FINGERPRINT_PURPOSE, value)


def fingerprint(value: str) -> str:
    """Skrót do zapisu — bieżącym kluczem."""

    return fingerprints(value)[0]


__all__ = [
    "FINGERPRINT_PURPOSE",
    "MASK",
    "PeselError",
    "birth_date",
    "checksum_ok",
    "clean",
    "fingerprint",
    "fingerprints",
    "last4",
    "masked",
    "sex",
]
