"""Krajowa Izba Rozliczeniowa — zamówienie z prozą „Zatrudnienie kontraktora".

Układ z korpusu::

    Zatrudnienie kontraktora - P. Konrad
    Niemyjski, stawka 210,00 zł netto/h = 1680.00
    zł netto/1 MD
    …
    Nazwa artykułu / 1.07.2026 - 30.09.2026 / … / Termin realizacji
    L.dz. KIR/DAZ/MD/01351/6/2026/DSR/ZAM

Stawka jest GODZINOWA („zł netto/h"); przeliczenie na MD w dokumencie
(„= 1680.00 zł netto/1 MD") ignorujemy — zapisujemy tak, jak klient rozlicza.
Nazwisko bywa przełamane na dwie linie i poprzedzone „P." — stąd DOTALL
i zdjęcie tytułu.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    clear_field,
    date_range_first,
    normalize_amount,
    set_field,
)

# Etykieta case-insensitive, WARTOŚĆ tylko wielkie litery/cyfry: pdfminer potrafi
# skleić numer z następnym słowem bez spacji („…/DSR/ZAMAl. Jerozolimskie"),
# a case-insensitive klasa zjadłaby „Al".
# Granica wartości: koniec ciągu WIELKICH liter/cyfr, albo miejsce, gdzie
# zaczyna się sklejone słowo („…/ZAM" + „Al." — wielka litera i zaraz mała).
_LDZ_RE = re.compile(
    r"(?i:L\.\s*dz\.?)\s*[:.]?\s*(KIR/[A-Z0-9/]+?)(?=[A-Z][a-z]|[^A-Z0-9/]|$)"
)
_HIRE_RE = re.compile(
    r"Zatrudnienie\s+kontraktora\s*[-–—]\s*(.+?),\s*stawka\s+"
    r"(\d[\d\s  .]*(?:,\d{1,2})?)\s*z[łl]\s*netto\s*/\s*h",
    re.IGNORECASE | re.DOTALL,
)


def order_number(text: str) -> Optional[str]:
    m = _LDZ_RE.search(text or "")
    return m.group(1).rstrip(".,") if m else None


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    rows: list[ConsultantOrderRow] = []
    start, end = date_range_first(text)
    for m in _HIRE_RE.finditer(text or ""):
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group(1)),
                rate_client=normalize_amount(m.group(2)),
                rate_unit="hour",
                start_date=start,
                end_date=end,
                uncertain=False,
            )
        )
    return rows


def apply_kir_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True

    start, end = date_range_first(document_text)
    if start and end:
        set_field(result, "start_date", start)
        set_field(result, "end_date", end)

    rows = extract_rows(document_text)
    if len(rows) == 1:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "rate_unit", "hour")
        # Jeden wiersz = stawka godzinowa tej osoby. Potwierdź dla enforce (P1).
        result.consultant_rate_matched = True
    else:
        clear_field(result, "rate_client")
        clear_field(result, "rate_unit")
    # Liczba MD z tabeli to przeliczenie stawki godzinowej — nie budżet.
    clear_field(result, "md_total")
    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    reasons: list[str] = []
    if result.title is None:
        reasons.append("Nie znaleziono numeru „L.dz. KIR/…” — sprawdź numer zamówienia")
    if not (start and end):
        reasons.append("Nie znaleziono okresu „od – do” — wpisz daty ręcznie")
    if len(rows) != 1:
        reasons.append(
            "Nie rozpoznano jednej stawki „zł netto/h” przy nazwisku — sprawdź stawkę"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result
