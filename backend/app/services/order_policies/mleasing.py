"""mLeasing — „Numer zamówienia DO/…", „Okres zatrudnienia od … do …".

Układ z korpusu::

    Numer zamówienia DO/CEO/CEO/25/013226
    …
    Nazwa: / BL(mL) - ‪‪‪Urszula Pasik, Tester / manualny - Regular, …
    Opis: / Okres zatrudnienia od 01.01.2026 r. / do 31.12.2026 r.

Przed nazwiskiem ekstrakcja z PDF wstawia znaki sterujące kierunkiem tekstu —
``clean_person_name`` je zdejmuje. Stawka („Cena jedn. netto") czytana po
etykiecie; jednostkę ustalamy tylko, gdy dokument ją podaje.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    _DATE,
    clean_person_name,
    clear_field,
    labelled_date,
    labelled_text,
    model_concerns,
    normalize_amount,
    normalize_date,
    set_field,
)

ORDER_NUMBER_LABEL = r"Numer\s+zam[óo]wienia"
# Nazwisko stoi po „BL(mL) -" (kod pozycji), a etykieta „Nazwa:" bywa w linii
# WYŻEJ i dzieli ją z innymi komórkami — kotwiczymy na kodzie pozycji.
_NAME_RE = re.compile(r"BL\s*\(\s*mL\s*\)\s*[-–—]\s*([^,\n]{3,80}),", re.IGNORECASE)
# Komórka pozycji: „225,00dzień 869,92 PLN" → ilość, jednostka, cena jednostkowa.
_UNIT_PRICE_RE = re.compile(
    r"(\d[\d\s  ]*(?:,\d{1,2})?)\s*(dzie[ńn]|dni|godz\w*|h\b|mies\w*|m-c)\s+"
    r"(\d[\d\s  .]*,\d{2})\s*PLN",
    re.IGNORECASE,
)
_UNIT_MAP = {
    "dzie": "day",
    "dni": "day",
    "godz": "hour",
    "h": "hour",
    "mies": "month",
    "m-c": "month",
}


def unit_price(text: str) -> tuple[Optional[Decimal], Optional[str]]:
    """(cena jednostkowa netto, jednostka) z komórki pozycji."""
    m = _UNIT_PRICE_RE.search(text or "")
    if not m:
        return None, None
    unit_token = m.group(2).lower()
    unit = next((u for k, u in _UNIT_MAP.items() if unit_token.startswith(k)), None)
    return normalize_amount(m.group(3)), unit


def order_number(text: str) -> Optional[str]:
    return labelled_text(ORDER_NUMBER_LABEL, text)


_PERIOD_RE = re.compile(
    r"Okres\s+zatrudnienia\s+od[^\d\n]{0,40}?" + _DATE + r"[^\n]*\n?[^\n]*?\bdo\b"
    r"[^\d\n]{0,40}?" + _DATE,
    re.IGNORECASE,
)

MULTIPLE_RATES_REASON = (
    "Pozycje dokumentu mają różne ceny jednostkowe (albo nie każda ma cenę) — "
    "przypisz stawkę każdej osobie ręcznie"
)
MULTIPLE_PERIODS_REASON = (
    "Pozycje dokumentu mają różne okresy zatrudnienia (albo nie każda ma okres) — "
    "wpisz daty każdej osobie ręcznie"
)


def _unit_prices(text: str) -> list[tuple[Optional[Decimal], Optional[str]]]:
    return [unit_price(m.group(0)) for m in _UNIT_PRICE_RE.finditer(text or "")]


def _periods(text: str) -> list[tuple[Optional[str], Optional[str]]]:
    return [
        (normalize_date(m.group(1), end=False), normalize_date(m.group(2), end=True))
        for m in _PERIOD_RE.finditer(text or "")
    ]


def _shared(values: list, positions: int):
    """Wartość wspólna wszystkich pozycji albo ``None``.

    Runda 7 (R7-N4-1): dawniej pierwsza cena i pierwszy okres dokumentu szły do
    KAŻDEJ osoby, a wiersze były pewne — druga osoba dostawała stawkę pierwszej,
    a „tabela” potwierdzała ten błąd modelowi. Przy kilku osobach wartość
    obowiązuje tylko wtedy, gdy każda pozycja ma ją i jest taka sama.
    """
    if not values:
        return None
    if positions > 1 and (len(values) != positions or len(set(values)) != 1):
        return None
    return values[0]


def _names(text: str) -> list[str]:
    names = [clean_person_name(m.group(1)) for m in _NAME_RE.finditer(text or "")]
    return [name for name in names if len(name.split()) >= 2]


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    names = _names(text)
    period = _shared(_periods(text), len(names))
    if period is None and len(names) <= 1:
        # Jedna pozycja: okres bywa rozbity inaczej niż „od … do …” w jednym
        # dopasowaniu — zostaje dotychczasowy odczyt po etykietach.
        period = (
            labelled_date(r"Okres\s+zatrudnienia\s+od", text),
            labelled_date(
                r"Okres\s+zatrudnienia\s+od[^\n]*\n?[^\n]*?\bdo\b", text, end=True
            ),
        )
    start, end = period or (None, None)
    rate, unit = _shared(_unit_prices(text), len(names)) or (None, None)
    rows: list[ConsultantOrderRow] = []
    for name in names:
        reasons = []
        if rate is None and len(names) > 1:
            reasons.append(MULTIPLE_RATES_REASON)
        if period is None and len(names) > 1:
            reasons.append(MULTIPLE_PERIODS_REASON)
        rows.append(
            ConsultantOrderRow(
                consultant_name=name,
                start_date=start,
                end_date=end,
                rate_client=rate,
                rate_unit=unit,
                uncertain=rate is None or bool(reasons),
                uncertain_reason="; ".join(reasons) or None,
            )
        )
    return rows


def apply_mleasing_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True

    rows = extract_rows(document_text)
    if len(rows) > 1:
        # Kilka osób: wartość dokumentu tylko wspólna dla wszystkich pozycji
        # (``extract_rows``); inaczej pole nie może udawać stawki każdej osoby.
        start, end = rows[0].start_date, rows[0].end_date
        rate, unit = rows[0].rate_client, rows[0].rate_unit
        if not (start and end):
            clear_field(result, "start_date")
            clear_field(result, "end_date")
        if rate is None:
            clear_field(result, "rate_client")
    else:
        start = labelled_date(r"Okres\s+zatrudnienia\s+od", document_text)
        end = labelled_date(
            r"Okres\s+zatrudnienia\s+od[^\n]*\n?[^\n]*?\bdo\b",
            document_text,
            end=True,
        )
        rate, unit = unit_price(document_text)
    if start:
        set_field(result, "start_date", start)
    if end:
        set_field(result, "end_date", end)
    if rate is not None:
        set_field(result, "rate_client", rate)
        if unit:
            set_field(result, "rate_unit", unit)
    clear_field(result, "md_total")

    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    # Zastrzeżenia modelu zostają — reguła ich nie zastępuje (runda 6 audytu).
    reasons: list[str] = model_concerns(result)
    if result.title is None:
        reasons.append("Nie znaleziono pola „Numer zamówienia” — sprawdź numer")
    row_reasons = [
        part
        for r in rows
        if r.uncertain_reason
        for part in r.uncertain_reason.split("; ")
    ]
    if not (start and end) and MULTIPLE_PERIODS_REASON not in row_reasons:
        reasons.append(
            "Nie znaleziono „Okres zatrudnienia od … do …” — wpisz daty ręcznie"
        )
    if rate is None and MULTIPLE_RATES_REASON not in row_reasons:
        reasons.append(
            "Nie znaleziono ceny jednostkowej pozycji („… dzień 869,92 PLN”) — sprawdź stawkę"
        )
    reasons.extend(row_reasons)
    result.uncertain_reasons = list(dict.fromkeys(reasons))
    result.uncertain = bool(reasons)
    return result
