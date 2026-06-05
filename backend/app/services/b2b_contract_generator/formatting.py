"""Formatery dla Generatora Umów B2B (filtr Jinja współdzielony HTML + DOCX).

Moduł-liść: nie importuje niczego z `app` (zapobiega cyklom importów, bo
`contract_templates` rejestruje stąd filtr `pl_date`).
"""

from __future__ import annotations

from datetime import date, datetime

# Wizualny placeholder dla niewypełnionej daty (jak blank „…" w oryginale).
_DATE_BLANK = "…………………"


def pl_date(value: object) -> str:
    """Sformatuj datę jako DD.MM.YYYY; None/pusty → placeholder kropkowy."""
    if value is None or value == "":
        return _DATE_BLANK
    if isinstance(value, str):
        return value
    if isinstance(value, (date, datetime)):
        return f"{value.day:02d}.{value.month:02d}.{value.year}"
    return str(value)
