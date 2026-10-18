"""Tytuły przelewów do ludzi z zespołu.

* faktura z KSeF — numer faktury i numer KSeF (od 1.01.2027 numer KSeF
  w tytule jest obowiązkowy; dziś ułatwia rozpoznanie zapłaty na wyciągu),
* faktura PDF dopięta ręcznie (poza KSeF do końca 2026) — numer faktury,
* zlecenie — „Wynagrodzenie zlecenie MM/RRRR”, UoP — „Wynagrodzenie MM/RRRR”.

Elixir-O mieści 4 linie po 35 znaków: numer KSeF (35 znaków) idzie w osobnej
linii (``title_lines``), więc nie jest nigdy przecięty.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Optional

LINE_LENGTH = 35
MAX_LINES = 4
#: ``NIP-RRRRMMDD-XXXXXXXXXXXX-XX`` — numer nadany przez KSeF.
KSEF_NUMBER = re.compile(r"\b\d{10}-\d{8}-[0-9A-F]{12}-[0-9A-F]{2}\b")
#: Znaki, które psują plik paczki (separator linii Elixir, cudzysłów pola).
_UNSAFE = re.compile(r'[|"\r\n\t\x00-\x1f]')


@dataclass(frozen=True)
class InvoiceRef:
    invoice_number: str
    ksef_number: Optional[str]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", _UNSAFE.sub(" ", text or "")).strip()


def transfer_title(
    employment_type: str,
    year: int,
    month: int,
    invoices: Sequence[InvoiceRef] = (),
) -> str:
    """Jeden tytuł (CSV, lista dla Finansów); linie Elixir z ``title_lines``."""

    return " ".join(title_lines(employment_type, year, month, invoices))


def title_lines(
    employment_type: str,
    year: int,
    month: int,
    invoices: Sequence[InvoiceRef] = (),
) -> list[str]:
    period = f"{month:02d}/{year}"
    if employment_type != "b2b" or not invoices:
        words = (
            "Wynagrodzenie zlecenie"
            if employment_type == "zlecenie"
            else ("Wynagrodzenie")
        )
        return [f"{words} {period}"]
    lines: list[str] = []
    for ref in invoices:
        number = clean(ref.invoice_number)[:LINE_LENGTH]
        if number:
            lines.append(number)
        if ref.ksef_number:
            lines.append(ref.ksef_number[:LINE_LENGTH])
    return lines[:MAX_LINES] or [f"Faktura {period}"]


def ksef_numbers_in(text: str) -> list[str]:
    """Numery KSeF z tytułu wyciągu (wielkie litery jak w KSeF)."""

    return list(dict.fromkeys(KSEF_NUMBER.findall((text or "").upper())))


__all__ = [
    "InvoiceRef",
    "KSEF_NUMBER",
    "LINE_LENGTH",
    "MAX_LINES",
    "clean",
    "ksef_numbers_in",
    "title_lines",
    "transfer_title",
]
