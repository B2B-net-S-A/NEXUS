"""Alior Bank — „Zamówienie nr: OIT/…", tabela Konsultantów z trzema stawkami.

Układ z pipeline'u (pdfplumber). Numer umowy ramowej powtarza się na KAŻDEJ
stronie i stoi PRZED numerem zamówienia::

    Do Umowy Ramowej: OIT/0258/2023/ITVM        ← NIE numer zamówienia
    Zamówienie nr: OIT/0189/2026/ITVM           ← numer zamówienia
    …
    Wiktoria
    Matyja Business
    1 189 1 155,00 13,81% 1 340,00 253 260,00 zł
    (01.04.2026- Analyst
    31.12.2026)
    …
    5. Moment wejścia w życie Zamówienia: 01.04.2026
    czas oznaczony: 31.12.2026 lub do wyczerpania

Wiersz liczbowy jest JEDNOZNACZNY: L.P., Roboczodni, stawka bazowa, marża %,
**Razem stawka dla Banku** (to jest stawka klienta — czwarta liczba, nie
pierwsza), Total. Nazwisko jest rozsypane po sąsiednich liniach razem ze
słowami profilu, więc deterministycznie dajemy rzetelnie PIENIĄDZE per pozycja,
a nazwisko jako najlepszy odczyt — tożsamość osoby potwierdza model
(zweryfikowany przez roster), stawkę potwierdza ta tabela.
„lub do wyczerpania kwoty zamówienia" NIE jest datą.
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
    money_after,
    normalize_amount,
    normalize_date,
    set_field,
)

_ORDER_NUMBER_RE = re.compile(
    r"Zam[óo]wienie\s+nr\s*:?\s*(OIT/[A-Z0-9/]+)", re.IGNORECASE
)
_AMT = r"\d[\d  ]*,\d{2}"
_WORD = r"[A-Za-zĄąĆćĘęŁłŃńÓóŚśŹźŻż/]+"
# L.P., opcjonalnie fragment okresu „(01.04.2026-" (WYMAGA nawiasu i daty — gołe
# cyfry to już Roboczodni), opcjonalnie słowa profilu, potem: Roboczodni, stawka
# bazowa, marża %, Razem stawka dla Banku, Total. Tylko poziome białe znaki —
# dopasowanie idzie po pojedynczej linii.
_NUMERIC_ROW_RE = re.compile(
    rf"^(?P<lp>\d{{1,2}})[ \t]+"
    rf"(?:\(\d{{1,2}}\.\d{{1,2}}\.\d{{4}}[-–]?\)?[ \t]+)?"
    rf"(?:{_WORD}(?:[ \t]+{_WORD})*[ \t]+)?"
    rf"(?P<md>\d{{1,4}})[ \t]+(?P<base>{_AMT})[ \t]+(?P<margin>\d{{1,2}},\d{{2}})%[ \t]+"
    rf"(?P<rate>{_AMT})[ \t]+(?P<total>{_AMT})[ \t]*z[łl]"
)
# Początek okresu „(dd.mm.rrrr-" i koniec „dd.mm.rrrr)" bywają rozdzielone
# słowem profilu albo całym wierszem liczbowym — szukane osobno w oknie.
_PERIOD_START_RE = re.compile(r"\((\d{1,2}\.\d{1,2}\.\d{4})\s*[-–]")
_PERIOD_END_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\)")
_PROFILE_WORDS = {
    "business",
    "analyst",
    "senior",
    "mobile",
    "engineer",
    "developer",
    "backend",
    "frontend",
    "junior",
    "regular",
    "tester",
    "architekt",
    "architect",
    "devops",
    "programista",
    "analityk",
    "lead",
    "qa",
    "manager",
    "specialist",
    "specjalista",
}
_MAX_TOTAL_LABEL = r"Maksymalna\s+warto[śs][ćc]\s+Zam[óo]wienia"


def order_number(text: str) -> Optional[str]:
    m = _ORDER_NUMBER_RE.search(text or "")
    return m.group(1).rstrip(".,") if m else None


def _name_before(lines: list[str], idx: int) -> tuple[str, bool]:
    """Najlepszy odczyt nazwiska z ≤2 linii przed wierszem liczbowym."""
    tokens: list[str] = []
    for ln in lines[max(0, idx - 2) : idx]:
        for tok in ln.split():
            low = tok.lower().strip("()")
            if low in _PROFILE_WORDS or re.search(r"\d", tok):
                continue
            tokens.append(tok)
    name = clean_person_name(" ".join(tokens))
    return name, len(name.split()) != 2


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    lines = (text or "").splitlines()
    rows: list[ConsultantOrderRow] = []
    for idx, ln in enumerate(lines):
        m = _NUMERIC_ROW_RE.match(ln.strip())
        if not m:
            continue
        window = "\n".join(lines[max(0, idx - 2) : idx + 3])
        pm_start = _PERIOD_START_RE.search(window)
        pm_end = _PERIOD_END_RE.search(window, pm_start.end()) if pm_start else None
        name, name_uncertain = _name_before(lines, idx)
        rows.append(
            ConsultantOrderRow(
                consultant_name=name or f"(pozycja {m.group('lp')})",
                start_date=normalize_date(pm_start.group(1), end=False)
                if pm_start
                else None,
                end_date=normalize_date(pm_end.group(1), end=True) if pm_end else None,
                md_total=normalize_amount(m.group("md")),
                rate_client=normalize_amount(m.group("rate")),
                rate_unit="day",
                uncertain=name_uncertain,
                uncertain_reason=(
                    "Nazwisko rozsypane po liniach tabeli — potwierdź osobę"
                    if name_uncertain
                    else None
                ),
            )
        )
    return rows


def max_total(text: str) -> Optional[Decimal]:
    return money_after(_MAX_TOTAL_LABEL, text)


def apply_alior_order_policy(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    number = order_number(document_text)
    if number:
        set_field(result, "title", number)
        result.title_needs_review = False
    else:
        clear_field(result, "title")
        result.title_needs_review = True

    start = labelled_date(
        r"Moment\s+wej[śs]cia\s+w\s+[żz]ycie\s+Zam[óo]wienia", document_text
    )
    end = labelled_date(r"czas\s+oznaczony", document_text, end=True)
    if start:
        set_field(result, "start_date", start)
    if end:
        set_field(result, "end_date", end)

    rows = extract_rows(document_text)
    totals_ok: Optional[bool] = None
    max_value = max_total(document_text)
    if rows and max_value is not None:
        computed = sum((r.md_total or 0) * (r.rate_client or 0) for r in rows)
        totals_ok = computed == max_value
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
        reasons.append(
            "Nie znaleziono pola „Zamówienie nr:” (OIT/…) — sprawdź numer zamówienia"
        )
    if not (start and end):
        reasons.append(
            "Nie znaleziono „Moment wejścia w życie” / „czas oznaczony” — wpisz daty ręcznie"
        )
    if not rows:
        reasons.append("Nie rozpoznano tabeli Konsultantów — wpisz osoby ręcznie")
    if totals_ok is False:
        reasons.append(
            "Σ(Roboczodni × Razem stawka) ≠ „Maksymalna wartość Zamówienia” — sprawdź wiersze"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result
