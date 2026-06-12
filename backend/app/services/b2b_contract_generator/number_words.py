"""Liczba → słownie (PL + EN) dla „stawki słownie" w umowie B2B.

Obsługuje 0–999 999 (z zapasem dla stawek godzinowych). Forma mianownikowa.
"""

from __future__ import annotations

_PL_ONES = [
    "zero",
    "jeden",
    "dwa",
    "trzy",
    "cztery",
    "pięć",
    "sześć",
    "siedem",
    "osiem",
    "dziewięć",
]
_PL_TEENS = [
    "dziesięć",
    "jedenaście",
    "dwanaście",
    "trzynaście",
    "czternaście",
    "piętnaście",
    "szesnaście",
    "siedemnaście",
    "osiemnaście",
    "dziewiętnaście",
]
_PL_TENS = [
    "",
    "",
    "dwadzieścia",
    "trzydzieści",
    "czterdzieści",
    "pięćdziesiąt",
    "sześćdziesiąt",
    "siedemdziesiąt",
    "osiemdziesiąt",
    "dziewięćdziesiąt",
]
_PL_HUNDREDS = [
    "",
    "sto",
    "dwieście",
    "trzysta",
    "czterysta",
    "pięćset",
    "sześćset",
    "siedemset",
    "osiemset",
    "dziewięćset",
]


def _pl_under_1000(n: int) -> str:
    parts: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(_PL_HUNDREDS[h])
    if 10 <= rest < 20:
        parts.append(_PL_TEENS[rest - 10])
    else:
        tn, o = divmod(rest, 10)
        if tn:
            parts.append(_PL_TENS[tn])
        if o:
            parts.append(_PL_ONES[o])
    return " ".join(parts)


def _pl_thousands(n: int) -> str:
    if n == 1:
        return "tysiąc"
    last, last2 = n % 10, n % 100
    word = "tysiące" if (2 <= last <= 4 and not (12 <= last2 <= 14)) else "tysięcy"
    return f"{_pl_under_1000(n)} {word}"


def liczba_slownie(num: int | float | None) -> str:
    if num is None:
        return ""
    n = int(abs(num))
    if n == 0:
        return "zero"
    th, rest = divmod(n, 1000)
    parts: list[str] = []
    if th:
        parts.append(_pl_thousands(th))
    if rest:
        parts.append(_pl_under_1000(rest))
    return " ".join(parts).strip()


_EN_ONES = [
    "zero",
    "one",
    "two",
    "three",
    "four",
    "five",
    "six",
    "seven",
    "eight",
    "nine",
]
_EN_TEENS = [
    "ten",
    "eleven",
    "twelve",
    "thirteen",
    "fourteen",
    "fifteen",
    "sixteen",
    "seventeen",
    "eighteen",
    "nineteen",
]
_EN_TENS = [
    "",
    "",
    "twenty",
    "thirty",
    "forty",
    "fifty",
    "sixty",
    "seventy",
    "eighty",
    "ninety",
]


def _en_under_1000(n: int) -> str:
    parts: list[str] = []
    h, rest = divmod(n, 100)
    if h:
        parts.append(f"{_EN_ONES[h]} hundred")
    if 10 <= rest < 20:
        parts.append(_EN_TEENS[rest - 10])
    else:
        tn, o = divmod(rest, 10)
        if tn:
            parts.append(_EN_TENS[tn])
        if o:
            parts.append(_EN_ONES[o])
    return " ".join(parts)


def number_to_words_en(num: int | float | None) -> str:
    if num is None:
        return ""
    n = int(abs(num))
    if n == 0:
        return "zero"
    th, rest = divmod(n, 1000)
    parts: list[str] = []
    if th:
        parts.append(f"{_en_under_1000(th)} thousand")
    if rest:
        parts.append(_en_under_1000(rest))
    return " ".join(parts).strip()


def _pl_zloty(n: int) -> str:
    """Poprawna forma „złoty" dla liczby: 1→złoty, 2-4→złote, reszta→złotych."""
    if n == 1:
        return "złoty"
    last, last2 = n % 10, n % 100
    if 2 <= last <= 4 and not (12 <= last2 <= 14):
        return "złote"
    return "złotych"


def _pl_grosz(n: int) -> str:
    """Poprawna forma „grosz" dla liczby: 1→grosz, 2-4→grosze, reszta→groszy."""
    if n == 1:
        return "grosz"
    last, last2 = n % 10, n % 100
    if 2 <= last <= 4 and not (12 <= last2 <= 14):
        return "grosze"
    return "groszy"


def _grosze_part(amount: int | float) -> int:
    """Część groszowa kwoty (zaokrąglona do pełnych groszy), 0–99."""
    whole = int(abs(amount))
    return int(round((abs(amount) - whole) * 100))


def rate_in_words(
    amount: int | float | None, language: str, currency: str = "PLN"
) -> str:
    """Stawka słownie z jednostką waluty ('pl' | 'en').

    PLN → „sto dwadzieścia złotych" / „one hundred twenty zlotys". Stawka
    ułamkowa dolicza grosze: 135,50 → „sto trzydzieści pięć złotych pięćdziesiąt
    groszy" (umowa wymaga, by słownie odpowiadało kwocie liczbowej). Inna waluta
    → słownie + kod waluty (np. „... EUR"), bez części ułamkowej.
    """
    if amount is None:
        return ""
    n = int(abs(amount))
    cur = (currency or "PLN").upper()
    grosze = _grosze_part(amount) if cur == "PLN" else 0
    if language == "en":
        words = number_to_words_en(amount)
        unit = "zlotys" if cur == "PLN" else cur
        out = f"{words} {unit}".strip()
        if grosze:
            out += f" {number_to_words_en(grosze)} groszy"
        return out
    words = liczba_slownie(amount)
    unit = _pl_zloty(n) if cur == "PLN" else cur
    out = f"{words} {unit}".strip()
    if grosze:
        out += f" {liczba_slownie(grosze)} {_pl_grosz(grosze)}"
    return out
