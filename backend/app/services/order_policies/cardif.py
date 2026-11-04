"""Cardif (BNP Paribas Cardif) — „Zamówienie z dnia …", tabela specjalistów, stawka w prozie.

Układ z pipeline'u::

    Zamówienie z dnia 27.04.2026 do umowy ramowej z dnia 3 lipca 2017 (Time and Material)
    …
    LP Grupa kompetencyjna Od Do Liczba MD
    1. Jakub Jedynak 27.04.2026 31.12.2026 172
    …
    9. Daty od do wskazują okres, w którym będą wykorzystane 172MDs przy zastosowaniu stawki dla Testera
    Manualnego (1040 PLN/MD net.).

Dokument nie ma numeru — identyfikatorem jest data z „Zamówienie z dnia"
(ticket). Zamówienie jest OKRESOWE: liczba MD z tabeli i z prozy jest
informacją, nie budżetem (ticket: „system nie patrzy na liczbę MD"). Stawka
to liczba w nawiasie „(… PLN/MD net.)".
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    clear_field,
    model_concerns,
    normalize_amount,
    normalize_date,
    set_field,
)

_ORDER_DATE_RE = re.compile(
    r"Zam[óo]wienie\s+z\s+dnia\s+(\d{1,2}\.\d{1,2}\.\d{4})", re.IGNORECASE
)
_DATE = r"\d{1,2}\.\d{1,2}\.\d{4}"
_ROW_RE = re.compile(
    rf"^[ \t]*\d{{1,2}}\.[ \t]+(?P<name>[^\d\n]{{3,80}}?)[ \t]+(?P<start>{_DATE})[ \t]+(?P<end>{_DATE})[ \t]+(?P<md>\d+)[ \t]*$",
    re.MULTILINE,
)
_RATE_RE = re.compile(
    r"\((\d[\d\s  ]*(?:,\d{1,2})?)\s*PLN\s*/\s*MD\s*net", re.IGNORECASE
)


def order_number(text: str) -> Optional[str]:
    m = _ORDER_DATE_RE.search(text or "")
    return m.group(1) if m else None


def md_rates(text: str) -> list:
    """Różne stawki „(… PLN/MD net.)" w kolejności wystąpienia."""
    rates = (normalize_amount(m.group(1)) for m in _RATE_RE.finditer(text or ""))
    return list(dict.fromkeys(rate for rate in rates if rate is not None))


def md_rate(text: str):
    """Stawka dokumentu — wyłącznie gdy jest JEDNA.

    Kilka różnych stawek (np. osobno dla Testera i Analityka) nie mówi, która
    należy do której osoby; pierwsza z brzegu trafiała do każdego wiersza
    (runda 6 audytu) — teraz ``None`` i wiersze do sprawdzenia.
    """
    rates = md_rates(text)
    return rates[0] if len(rates) == 1 else None


def _rate_concern(text: str) -> Optional[str]:
    rates = md_rates(text)
    if len(rates) > 1:
        return (
            "W dokumencie są różne stawki ("
            + ", ".join(f"{rate} PLN/MD" for rate in rates)
            + ") — przypisz stawkę tej osobie ręcznie"
        )
    if not rates:
        return "Nie znaleziono stawki „(… PLN/MD net.)” w opisie — sprawdź stawkę"
    return None


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    rate = md_rate(text)
    concern = _rate_concern(text)
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_RE.finditer(text or ""):
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group("name")),
                start_date=normalize_date(m.group("start"), end=False),
                end_date=normalize_date(m.group("end"), end=True),
                rate_client=rate,
                rate_unit="day" if rate is not None else None,
                md_total=None,  # okresowe — MD informacyjne, nie budżet
                uncertain=rate is None,
                uncertain_reason=concern if rate is None else None,
            )
        )
    return rows


def apply_cardif_order_policy(
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
    rate = md_rate(document_text)
    if len(rows) == 1:
        set_field(result, "start_date", rows[0].start_date)
        set_field(result, "end_date", rows[0].end_date)
    if rate is not None:
        set_field(result, "rate_client", rate)
        set_field(result, "rate_unit", "day")
    else:
        clear_field(result, "rate_client")
        clear_field(result, "rate_unit")
    clear_field(result, "md_total")
    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    # Zastrzeżenia modelu zostają (runda 6 audytu) — do tej poprawki reguła
    # zastępowała je w całości, więc np. nieczytelne nazwisko znikało. Odpada
    # tylko „brak liczby MD": MD u Cardif jest informacją, nie budżetem.
    reasons: list[str] = model_concerns(result)
    if result.title is None:
        reasons.append(
            "Nie znaleziono „Zamówienie z dnia …” — sprawdź identyfikator zamówienia"
        )
    if not rows:
        reasons.append(
            "Nie rozpoznano tabeli specjalistów (Od/Do) — wpisz osoby i daty ręcznie"
        )
    concern = _rate_concern(document_text)
    if concern is not None:
        reasons.append(concern)
    result.uncertain_reasons = list(dict.fromkeys(reasons))
    result.uncertain = bool(reasons)
    return result
