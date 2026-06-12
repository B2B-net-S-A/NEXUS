"""Formatery dla Generatora Umów B2B (filtr Jinja współdzielony HTML + DOCX).

Moduł-liść: nie importuje niczego z `app` (zapobiega cyklom importów, bo
`contract_templates` rejestruje stąd filtr `pl_date`).
"""

from __future__ import annotations

from datetime import date, datetime

# Wizualny placeholder dla niewypełnionej daty (jak blank „…" w oryginale).
_DATE_BLANK = "…………………"


def format_rate(amount: object) -> str | None:
    """Stawka do wyświetlenia w umowie: liczba całkowita → „150"; ułamkowa →
    polski zapis z przecinkiem i dwoma miejscami → „135,50".

    None → None (szablon pokazuje wtedy placeholder „…")."""
    if amount is None or amount == "":
        return None
    try:
        value = float(amount)
    except (TypeError, ValueError):
        return str(amount)
    if value == int(value):
        return str(int(value))
    return f"{value:.2f}".replace(".", ",")


def pl_date(value: object) -> str:
    """Sformatuj datę jako DD.MM.YYYY; None/pusty → placeholder kropkowy."""
    if value is None or value == "":
        return _DATE_BLANK
    if isinstance(value, str):
        return value
    if isinstance(value, (date, datetime)):
        return f"{value.day:02d}.{value.month:02d}.{value.year}"
    return str(value)


# §13 — fraza daty rozpoczęcia świadczenia Usług wg trybu wybranego w UI.
_START_PREFIX = {
    "pl": {
        "exact": "z dniem",
        "not_earlier": "nie wcześniej niż",
        "not_later": "nie później niż",
    },
    "en": {
        "exact": "on",
        "not_earlier": "no earlier than",
        "not_later": "no later than",
    },
}


def start_clause(value: object, mode: str | None, language: str | None) -> str:
    """„z dniem 01.04.2026" / „nie wcześniej niż …" / „nie później niż …"."""
    lang = "en" if (language or "pl").lower().startswith("en") else "pl"
    prefixes = _START_PREFIX[lang]
    prefix = prefixes.get((mode or "exact"), prefixes["exact"])
    return f"{prefix} {pl_date(value)}"
