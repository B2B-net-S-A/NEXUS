"""VeloBank — „Zamówienie nr", tabela „Dane wykonawców" z okresem i stawką per wiersz.

Układ z pipeline'u (pdfplumber; WIERSZ tabeli w jednej linii)::

    Zamówienie nr 3/07/2026/BL
    …
    1. Dane wykonawców:
    Rodzaj kompetencji Zlecenie od Zlecenie do Liczba Stawka Wartość
    Nazwisko i imię Wartość brutto
    (profil) (dd-mm-rrrr) (dd-mm-rrrr) MD netto/MD netto
    Baczewski Marcin Starszy Tester 1.07.2026 31.08.2026 43 1 400,00 60 200,00 zł 74 046,00 zł
    …
    Wartość zlecenia
    518 150,00 PLN NETTO

Każda osoba ma WŁASNY okres i stawkę — w Nexusie każdy dostaje osobne
zamówienie (ticket). ``Nazwisko i imię`` = nazwisko PIERWSZE; zostawiamy jak
w dokumencie (matcher jest niewrażliwy na kolejność). Profil to wszystko między
nazwiskiem a pierwszą datą. Rachunek kontrolny: Σ(MD × stawka) = „Wartość
zlecenia … NETTO" — rozbieżność oznacza źle sparsowany wiersz.
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
    labelled_text,
    normalize_amount,
    normalize_date,
    set_field,
)

ORDER_NUMBER_LABEL = r"Zam[óo]wienie\s+nr\.?"
_DATE = r"\d{1,2}[./-]\d{1,2}[./-]\d{4}"
_AMT = r"\d[\d\s  ]*,\d{2}"
_ROW_RE = re.compile(
    rf"^(?P<name>\S+(?:-\S+)?[ \t]+\S+)[ \t]+(?P<profile>.*?)[ \t]+(?P<start>{_DATE})[ \t]+(?P<end>{_DATE})"
    rf"[ \t]+(?P<md>\d+(?:,\d+)?)[ \t]+(?P<rate>{_AMT})[ \t]+(?P<net>{_AMT})[ \t]*z[łl]",
    re.MULTILINE,
)
_TOTAL_NET_RE = re.compile(
    r"Warto[śs][ćc]\s+zlecenia[^\d]{0,80}?(\d[\d\s  ]*,\d{2})\s*PLN\s*NETTO",
    re.IGNORECASE | re.DOTALL,
)


def order_number(text: str) -> Optional[str]:
    return labelled_text(ORDER_NUMBER_LABEL, text)


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_RE.finditer(text or ""):
        rows.append(
            ConsultantOrderRow(
                consultant_name=clean_person_name(m.group("name")),
                start_date=normalize_date(m.group("start"), end=False),
                end_date=normalize_date(m.group("end"), end=True),
                md_total=normalize_amount(m.group("md")),
                rate_client=normalize_amount(m.group("rate")),
                rate_unit="day",
                uncertain=False,
            )
        )
    return rows


def total_net(text: str) -> Optional[Decimal]:
    m = _TOTAL_NET_RE.search(text or "")
    return normalize_amount(m.group(1)) if m else None


def rows_reconcile_with_total(
    rows: list[ConsultantOrderRow], total: Optional[Decimal]
) -> Optional[bool]:
    """Σ(MD × stawka) == wartość netto zlecenia? ``None`` gdy brak danych."""
    if total is None or not rows:
        return None
    try:
        computed = sum((r.md_total or 0) * (r.rate_client or 0) for r in rows)
    except TypeError:
        return None
    return computed == total


def apply_velobank_order_policy(
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
    reconciled = rows_reconcile_with_total(rows, total_net(document_text))
    starts = {r.start_date for r in rows if r.start_date}
    ends = {r.end_date for r in rows if r.end_date}
    # Okres dokumentu tylko, gdy wszyscy mają ten sam — inaczej okres jest per wiersz.
    if len(starts) == 1:
        set_field(result, "start_date", next(iter(starts)))
    if len(ends) == 1:
        set_field(result, "end_date", next(iter(ends)))
    if len(rows) == 1:
        set_field(result, "rate_client", rows[0].rate_client)
        set_field(result, "md_total", rows[0].md_total)
    else:
        clear_field(result, "rate_client")
        clear_field(result, "md_total")
    set_field(result, "rate_unit", "day")
    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    reasons: list[str] = []
    if result.title is None:
        reasons.append("Nie znaleziono pola „Zamówienie nr” — sprawdź numer zamówienia")
    if not rows:
        reasons.append("Nie rozpoznano tabeli „Dane wykonawców” — wpisz osoby ręcznie")
    if reconciled is False:
        reasons.append(
            "Σ(MD × stawka) z tabeli nie zgadza się z „Wartość zlecenia NETTO” — "
            "sprawdź wiersze osób"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result
