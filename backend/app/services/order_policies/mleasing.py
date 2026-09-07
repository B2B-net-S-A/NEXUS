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
    clean_person_name,
    clear_field,
    labelled_date,
    labelled_text,
    normalize_amount,
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


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    start = labelled_date(r"Okres\s+zatrudnienia\s+od", text)
    end = labelled_date(
        r"Okres\s+zatrudnienia\s+od[^\n]*\n?[^\n]*?\bdo\b", text, end=True
    )
    rate, unit = unit_price(text)
    rows: list[ConsultantOrderRow] = []
    for m in _NAME_RE.finditer(text or ""):
        name = clean_person_name(m.group(1))
        if len(name.split()) < 2:
            continue
        rows.append(
            ConsultantOrderRow(
                consultant_name=name,
                start_date=start,
                end_date=end,
                rate_client=rate,
                rate_unit=unit,
                uncertain=rate is None,
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

    start = labelled_date(r"Okres\s+zatrudnienia\s+od", document_text)
    end = labelled_date(
        r"Okres\s+zatrudnienia\s+od[^\n]*\n?[^\n]*?\bdo\b", document_text, end=True
    )
    if start:
        set_field(result, "start_date", start)
    if end:
        set_field(result, "end_date", end)
    rate, unit = unit_price(document_text)
    if rate is not None:
        set_field(result, "rate_client", rate)
        if unit:
            set_field(result, "rate_unit", unit)
        # Stawka pozycji z jednoosobowego zamówienia mLeasing — potwierdź dla
        # enforce (inaczej no-match matchera skasowałby poprawną stawkę, P1).
        result.consultant_rate_matched = True
    clear_field(result, "md_total")

    rows = extract_rows(document_text)
    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    reasons: list[str] = []
    if result.title is None:
        reasons.append("Nie znaleziono pola „Numer zamówienia” — sprawdź numer")
    if not (start and end):
        reasons.append(
            "Nie znaleziono „Okres zatrudnienia od … do …” — wpisz daty ręcznie"
        )
    if rate is None:
        reasons.append(
            "Nie znaleziono ceny jednostkowej pozycji („… dzień 869,92 PLN”) — sprawdź stawkę"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result
