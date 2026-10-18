"""Rachunek bankowy w Polsce: IBAN ``PL`` + 26 cyfr NRB.

Suma kontrolna IBAN (ISO 13616, mod 97) — ta sama, którą liczy bank przy
przelewie. NRB = 2 cyfry kontrolne + 8 cyfr numeru rozliczeniowego banku
+ 16 cyfr rachunku. Funkcje są czyste; numer rachunku nie trafia do wyjątków
ani logów (komunikat mówi tylko, co jest nie tak).
"""

from __future__ import annotations

import re
from typing import Optional

NRB_LENGTH = 26
_SPACES = re.compile(r"[\s-]+")
#: 26 cyfr (opcjonalnie z ``PL`` i spacjami co 4) — rachunek w tekście tytułu.
#: Numer KSeF ma myślniki i krótsze grupy cyfr, więc go nie łapie.
_ACCOUNT_IN_TEXT = re.compile(r"(?<!\d)(?:PL\s?)?(\d{2}(?:\s?\d{4}){6})(?!\d)")


class AccountError(ValueError):
    """Niepoprawny rachunek — komunikat bez numeru."""


def _mod97(digits: str) -> int:
    remainder = 0
    for start in range(0, len(digits), 9):
        remainder = int(f"{remainder}{digits[start : start + 9]}") % 97
    return remainder


def _iban_digits(country: str, check: str, bban: str) -> str:
    # Litery kraju: A=10 … Z=35 (P=25, L=21).
    letters = "".join(str(ord(char) - 55) for char in country)
    return f"{bban}{letters}{check}"


def iban_check_digits(bban: str, country: str = "PL") -> str:
    """Cyfry kontrolne IBAN dla 24 cyfr (numer banku + rachunek)."""

    return f"{98 - _mod97(_iban_digits(country, '00', bban)):02d}"


def normalize_nrb(raw: Optional[str]) -> str:
    """``PL61 1090 …`` / ``61109…`` → 26 cyfr NRB; zły numer = ``AccountError``."""

    value = _SPACES.sub("", (raw or "").strip()).upper()
    if value.startswith("PL"):
        value = value[2:]
    if not re.fullmatch(r"\d{26}", value):
        raise AccountError("Numer rachunku w Polsce ma 26 cyfr (opcjonalnie z PL).")
    if _mod97(_iban_digits("PL", value[:2], value[2:])) != 1:
        raise AccountError("Numer rachunku ma błędną sumę kontrolną.")
    return value


def is_valid_nrb(raw: Optional[str]) -> bool:
    try:
        normalize_nrb(raw)
    except AccountError:
        return False
    return True


def nrb_from_parts(sort_code: str, account: str) -> Optional[str]:
    """Rachunek złożony z numeru banku i numeru rachunku (pola 30 i 31 MT940).

    Bank podaje czasem 24 cyfry bez kontrolnych, czasem pełne 26 — kontrolne
    dopisujemy wtedy z sumy IBAN. Nie da się złożyć = ``None``.
    """

    digits = re.sub(r"\D", "", f"{sort_code}{account}")
    if len(digits) == 24:
        digits = iban_check_digits(digits) + digits
    return digits if is_valid_nrb(digits) else None


def mask_accounts(text: str) -> str:
    """Pełne numery rachunków w tekście → ``•• 1234`` (tytuły z wyciągu).

    Tytuł przelewu bywa zapisany w bazie i pokazany Płacom — pełny numer
    rachunku osoby nie może tam trafić (tylko 4 ostatnie cyfry).
    """

    def _mask(match: re.Match[str]) -> str:
        digits = re.sub(r"\D", "", match.group(1))
        return f"•• {digits[-4:]}"

    return _ACCOUNT_IN_TEXT.sub(_mask, text or "")


def last4(nrb: str) -> str:
    return nrb[-4:]


def bank_sort_code(nrb: str) -> str:
    """Numer rozliczeniowy banku (8 cyfr po cyfrach kontrolnych)."""

    return nrb[2:10]


def masked(nrb: Optional[str]) -> str:
    return f"•• {nrb[-4:]}" if nrb else "—"


def grouped_iban(nrb: str) -> str:
    """``PL61 1090 1014 …`` — zapis do pliku dla Finansów."""

    raw = f"PL{nrb}"
    return " ".join(raw[index : index + 4] for index in range(0, len(raw), 4))


__all__ = [
    "AccountError",
    "NRB_LENGTH",
    "bank_sort_code",
    "grouped_iban",
    "iban_check_digits",
    "is_valid_nrb",
    "last4",
    "mask_accounts",
    "masked",
    "normalize_nrb",
    "nrb_from_parts",
]
