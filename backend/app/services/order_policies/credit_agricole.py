"""Credit Agricole — warstwa dla układu pdfplumber: numer, okres, wiersz osoby.

Ciało polityki (stawka wyłącznie z „Wynagrodzenie za 1MD", MD z „Szacowana
ilość MD") zostaje w parserze. W układzie z pipeline'u NAGŁÓWKI tabeli są
rozbite po liniach, więc etykieta „Wynagrodzenie za 1MD" nie jest ciągła i
tamten ekstraktor nic nie znajduje. Wiersz osoby jest za to jednoznaczny::

    Zamówienie nr 26138 z dnia 2026-08-12 do Umowy Ramowej nr CA/B2B.NET/…
    …
    Podwin Wiktor Junior 54,00 700,00
    …
    Zamówienia - 2026-08-18 - 2026-10-31

= nazwisko, poziom, szacowana ilość MD, wynagrodzenie za 1 MD. Kolejność
kolumn jest stała (MD przed stawką) — dokładnie ta, którą polityka bazowa
chroni po etykietach. Zamówienie jest okresowe (MD szacunkowe → nie budżet).
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    normalize_amount,
    normalize_date,
    set_field,
)

_ORDER_NUMBER_RE = re.compile(r"Zam[óo]wienie\s+nr\s+(\d+)\s+z\s+dnia", re.IGNORECASE)
_PERIOD_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s*[-–]\s*(\d{4}-\d{2}-\d{2})")
_AMT = r"\d[\d\s  ]*,\d{2}"
_ROW_RE = re.compile(
    rf"^(?P<name>\S+[ \t]+\S+)[ \t]+(?P<level>Junior|Regular|Mid|Senior|Expert|Lead|Principal)[ \t]+"
    rf"(?P<md>{_AMT})[ \t]+(?P<rate>{_AMT})[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)


def order_number(text: str) -> Optional[str]:
    m = _ORDER_NUMBER_RE.search(text or "")
    return m.group(1) if m else None


def period(text: str) -> tuple[Optional[str], Optional[str]]:
    m = _PERIOD_RE.search(text or "")
    if not m:
        return None, None
    return normalize_date(m.group(1), end=False), normalize_date(m.group(2), end=True)


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    start, end = period(text)
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_RE.finditer(text or ""):
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group("name")),
                start_date=start,
                end_date=end,
                rate_client=normalize_amount(m.group("rate")),
                rate_unit="day",
                md_total=None,
                uncertain=False,
            )
        )
    return rows


def apply_credit_agricole_layout(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    start, end = period(document_text)
    if start and end:
        set_field(result, "start_date", start)
        set_field(result, "end_date", end)
    rows = extract_rows(document_text)
    if len(rows) == 1 and result.rate_client is None:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "rate_unit", "day")
        result.consultant_rate_matched = True
        result.uncertain_reasons = [
            r for r in result.uncertain_reasons if "Wynagrodzenie za 1MD" not in r
        ]
    if rows and not result.consultant_rows:
        result.consultant_rows = rows
    result.uncertain = bool(result.uncertain_reasons)
    return result
