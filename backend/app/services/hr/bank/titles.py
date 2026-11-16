"""Tytuły przelewów do ludzi z zespołu.

* faktura z KSeF — numer faktury i numer KSeF (od 1.01.2027 numer KSeF
  w tytule jest obowiązkowy, art. 108g VAT; dziś ułatwia rozpoznanie zapłaty
  na wyciągu),
* faktura PDF dopięta ręcznie (poza KSeF do końca 2026) — numer faktury,
* zlecenie — „Wynagrodzenie zlecenie MM/RRRR”, UoP — „Wynagrodzenie MM/RRRR”.

Elixir-O mieści 4 linie po 35 znaków: numer KSeF (35 znaków) idzie w osobnej
linii (``title_lines``), więc nie jest nigdy przecięty. Gdy faktury nie
mieszczą się w 4 liniach (faktura z korektami), numery faktur ustępują numerom
KSeF. Więcej niż 4 numery KSeF w jednym przelewie wymagają zbiorczego
identyfikatora KSeF, którego NEXUS nie generuje — od 1.01.2027 (data
płatności, nie dzień paczki) taki przelew jest odmową (``ksef_title_problem``),
tak samo jak faktura z KSeF bez zapisanego numeru KSeF.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Optional

LINE_LENGTH = 35
MAX_LINES = 4
#: ``NIP-RRRRMMDD-XXXXXXXXXXXX-XX`` — numer nadany przez KSeF.
KSEF_NUMBER = re.compile(r"\b\d{10}-\d{8}-[0-9A-F]{12}-[0-9A-F]{2}\b")
#: Znaki, które psują plik paczki (separator linii Elixir, cudzysłów pola).
_UNSAFE = re.compile(r'[|"\r\n\t\x00-\x1f]')
#: Od tej daty płatności numer KSeF w tytule przelewu jest obowiązkowy (art. 108g VAT).
KSEF_TITLE_FROM = date(2027, 1, 1)
KSEF_TITLE_LABELS: dict[str, str] = {
    "no_ksef_number": "Od 1.01.2027 tytuł przelewu faktury z KSeF musi mieć numer KSeF.",
    "ksef_title_overflow": "Od 1.01.2027 tytuł przelewu musi mieć numer KSeF każdej "
    f"faktury, a więcej niż {MAX_LINES} nie mieści się w przelewie. Zapłać faktury "
    "kilkoma przelewami albo zbiorczym identyfikatorem KSeF poza NEXUSEM.",
}


@dataclass(frozen=True)
class InvoiceRef:
    invoice_number: str
    ksef_number: Optional[str]
    #: Faktura przyszła z KSeF (``source='ksef'``) — wtedy numer KSeF musi być.
    from_ksef: bool = False


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
    if len(lines) > MAX_LINES:
        # Nie mieści się: numery KSeF przed numerami faktur (PDF spoza KSeF
        # zostaje przy numerze faktury, bo innego nie ma).
        ksef = [ref.ksef_number[:LINE_LENGTH] for ref in invoices if ref.ksef_number]
        rest = [
            clean(ref.invoice_number)[:LINE_LENGTH]
            for ref in invoices
            if not ref.ksef_number and clean(ref.invoice_number)
        ]
        lines = ksef + rest
    return lines[:MAX_LINES] or [f"Faktura {period}"]


def ksef_title_problem(invoices: Sequence[InvoiceRef], pay_date: date) -> Optional[str]:
    """Powód odmowy przelewu (klucz ``KSEF_TITLE_LABELS``) albo ``None``.

    Decyduje data płatności (data wykonania przelewu), nie dzień paczki.
    """

    if pay_date < KSEF_TITLE_FROM:
        return None
    if any(ref.from_ksef and not ref.ksef_number for ref in invoices):
        return "no_ksef_number"
    if len({ref.ksef_number for ref in invoices if ref.ksef_number}) > MAX_LINES:
        return "ksef_title_overflow"
    return None


def ksef_numbers_in(text: str) -> list[str]:
    """Numery KSeF z tytułu wyciągu (wielkie litery jak w KSeF)."""

    return list(dict.fromkeys(KSEF_NUMBER.findall((text or "").upper())))


__all__ = [
    "InvoiceRef",
    "KSEF_NUMBER",
    "KSEF_TITLE_FROM",
    "KSEF_TITLE_LABELS",
    "LINE_LENGTH",
    "MAX_LINES",
    "clean",
    "ksef_numbers_in",
    "ksef_title_problem",
    "title_lines",
    "transfer_title",
]
