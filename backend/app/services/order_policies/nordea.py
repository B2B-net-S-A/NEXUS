"""Nordea — warstwa dla układu pdfplumber: numer Call-Off, Initial Term, tabela osób.

Ciało polityki (``enforce_nordea_order_number``) zostaje w parserze; ta warstwa
działa PO nim i uzupełnia to, czego tamten ekstraktor w układzie z pipeline'u
nie widzi. W tym układzie trzy komórki nagłówka są PRZEPLECIONE po liniach::

    Nordea contact e-mail address Nordea Request number (if Frame Agreement Call Off
    applicable) number Agreement
    consultant.procurement@nordea.com number
    40517 CW2117535
    277157

„Call Off Agreement" jako ciąg występuje wyłącznie w TYTULE dokumentu (linia 2),
więc etykietowy ekstraktor trafia w okno po tytule i zwraca numer firmy
(``2858394-9``). Deterministyczna kotwica tego układu: wartości stoją w tej
samej kolejności co etykiety — numer Request, numer umowy ramowej (``CW…``),
a w NASTĘPNEJ linii, samotnie, numer Call-Off. Bierzemy więc pierwszą linię
złożoną z samych 5–7 cyfr po linii z tokenem ramowym.

Okres: „Initial Term ⏎ Start date End date ⏎ 2026-02-02 2026-11-30".
Osoby: „Łukasz Urbanowicz IT Operations - Senior Poland - 1 728 Hours 175,00 PLN
302 400,00 PLN" — ilość × stawka = subtotal (rachunek kontrolny).
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

_FRAME_TOKEN_RE = re.compile(r"\b[A-Z]{1,3}\d{5,}\b")
_STANDALONE_NUMBER_RE = re.compile(r"^\s*(\d{5,7})\s*$")
_TERM_HEADER_RE = re.compile(r"Start\s+date\s+End\s+date", re.IGNORECASE)
_TWO_ISO_RE = re.compile(r"(\d{4}-\d{2}-\d{2})\s+(\d{4}-\d{2}-\d{2})")
_AMT = r"\d[\d\s  ]*,\d{2}"
_ROW_RE = re.compile(
    rf"^(?P<name>\S+[ \t]+\S+(?:-\S+)?)[ \t]+(?P<rest>.*?)[ \t]+(?P<qty>\d[\d  ]*)[ \t]+(?P<unit>Hours?|Days?|Months?)"
    rf"[ \t]+(?P<rate>{_AMT})[ \t]*PLN[ \t]+(?P<sub>{_AMT})[ \t]*PLN[ \t]*$",
    re.MULTILINE | re.IGNORECASE,
)
_UNIT = {"hour": "hour", "day": "day", "month": "month"}


def call_off_number_interleaved(text: str) -> Optional[str]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _FRAME_TOKEN_RE.search(ln) and re.search(r"\b\d{4,6}\b", ln):
            for nxt in lines[i + 1 : i + 3]:
                m = _STANDALONE_NUMBER_RE.match(nxt)
                if m:
                    return m.group(1)
    return None


def initial_term(text: str) -> tuple[Optional[str], Optional[str]]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _TERM_HEADER_RE.search(ln):
            for nxt in lines[i + 1 : i + 3]:
                m = _TWO_ISO_RE.search(nxt)
                if m:
                    return normalize_date(m.group(1), end=False), normalize_date(
                        m.group(2), end=True
                    )
    return None, None


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    start, end = initial_term(text)
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_RE.finditer(text or ""):
        qty = normalize_amount(m.group("qty"))
        rate = normalize_amount(m.group("rate"))
        sub = normalize_amount(m.group("sub"))
        unit_key = m.group("unit").lower().rstrip("s")
        reconciled = (
            qty is not None
            and rate is not None
            and sub is not None
            and qty * rate == sub
        )
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group("name")),
                start_date=start,
                end_date=end,
                rate_client=rate,
                rate_unit=_UNIT.get(unit_key),
                md_total=qty if unit_key == "day" else None,
                uncertain=not reconciled,
                uncertain_reason=None
                if reconciled
                else "Ilość × stawka ≠ Subtotal — sprawdź wiersz",
            )
        )
    return rows


def apply_nordea_layout(result: OrderExtraction, document_text: str) -> OrderExtraction:
    """Uzupełnij wynik po ``enforce_nordea_order_number`` o układ z pipeline'u.

    Gdy kotwica przeplecionego układu TRAFIA, nadpisuje numer z ekstraktora
    etykietowego nawet wtedy, gdy tamten coś zwrócił: w tym układzie „Call Off
    Agreement" jako ciąg występuje wyłącznie w tytule dokumentu, więc okno po
    etykiecie niesie numer FIRMY (``2858394-9``), a nie zamówienia. Kotwica
    (linia z tokenem ramowym ``CW…`` + samotny numer pod nią) jest sygnaturą
    dokładnie tego układu, w którym ekstraktor etykietowy jest znany jako błędny.
    """
    number = call_off_number_interleaved(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
        result.uncertain_reasons = [
            r for r in result.uncertain_reasons if "Call Off Agreement number" not in r
        ]
    start, end = initial_term(document_text)
    if start and end:
        set_field(result, "start_date", start)
        set_field(result, "end_date", end)
    rows = extract_rows(document_text)
    if len(rows) == 1 and not rows[0].uncertain:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "rate_unit", rows[0].rate_unit)
        result.consultant_rate_matched = True
    if rows and not result.consultant_rows:
        result.consultant_rows = rows
    result.uncertain = bool(result.uncertain_reasons)
    return result
