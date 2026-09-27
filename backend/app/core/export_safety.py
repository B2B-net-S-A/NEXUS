"""Ochrona eksportów CSV/XLSX przed wstrzyknięciem formuły (CSV injection).

Tekst w eksportach pochodzi od ludzi — także anonimowych: imię, nazwisko
i lokalizacja kandydata przychodzą z publicznego formularza strony kariery,
nazwy klientów i numery zamówień z importów i maili. Komórka zaczynająca się
od ``=`` (albo ``+``, ``-``, ``@``) jest w Excelu formułą: ``=HYPERLINK(…)``
w polu „imię” zamienia plik w link do cudzego serwera, a openpyxl zapisuje
taki napis wprost jako formułę.

Reguła OWASP: tekst zaczynający się od ``= + - @``, tabulatora albo powrotu
karetki dostaje prefiks ``'`` — Excel i LibreOffice traktują wtedy komórkę jako
tekst. Liczby, daty i ``None`` przechodzą bez zmian (zostają liczbami i datami
w arkuszu).

Runda 10 (R10-N13-1): tekst traci też znaki sterujące, których format XLSX
nie przyjmuje (``\x00``–``\x08``, ``\x0b``, ``\x0c``, ``\x0e``–``\x1f``).
openpyxl rzuca na nich ``IllegalCharacterError``, więc jedno imię
``Jan\x07`` z formularza kariery wywracało cały eksport błędem 500. Znaki są
usuwane PRZED sprawdzeniem prefiksu — ``\x07=HYPERLINK(…)`` po usunięciu
zaczyna się od ``=`` i też dostaje apostrof.

Każdy moduł w ``app/`` budujący CSV/XLSX z danych użytkownika woła
:func:`safe_cell` (pilnuje tego ``tests/test_export_safety_contract.py``).
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

# `\t` i `\r` na początku też uruchamiają interpretację w części arkuszy
# (OWASP „CSV Injection”), więc traktujemy je jak znak formuły.
FORMULA_PREFIXES: tuple[str, ...] = ("=", "+", "-", "@", "\t", "\r")

# Telefon „+48 600 100 200” i kwota „-1 200,50” zaczynają się od `+`/`-`, ale
# same cyfry i separatory nie wywołają funkcji ani linku — apostrof psułby
# tylko najczęstszą kolumnę eksportu kandydatów (telefon). `=` nie ma wyjątku.
_NUMBER_LIKE = re.compile(r"[+-][\d\s().,/-]*\d[\d\s().,/-]*")


def safe_cell(value: Any) -> Any:
    """Zwróć wartość bezpieczną do komórki arkusza.

    Tylko tekst jest zmieniany — liczby i daty zostają typami, które arkusz
    umie sortować i sumować.
    """

    if not isinstance(value, str):
        return value
    value = ILLEGAL_CHARACTERS_RE.sub("", value)
    if value.startswith(FORMULA_PREFIXES):
        if _NUMBER_LIKE.fullmatch(value):
            return value
        return f"'{value}"
    return value


def safe_row(values: Iterable[Any]) -> list[Any]:
    """:func:`safe_cell` dla każdej komórki wiersza."""

    return [safe_cell(value) for value in values]
