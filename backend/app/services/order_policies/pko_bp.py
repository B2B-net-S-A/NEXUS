"""PKO Bank Polski — „Zamówienie nr", tabela Wykonawców z okresem i stawką MD.

Układ z korpusu (nagłówki tabeli rozbite po jednym na linię, potem wiersze)::

    Zamówienie nr 1830/2026
    Zgodnie z postanowieniem Umowy ramowej numer DIT-2025-0005 …   ← NIE numer zamówienia
    1. Wykonawcy, Profile, Terminy, Stawki:
    Imię i nazwisko / Wykonawców / Profil / Początek / Zaangażowania /
    Planowany Koniec / Zaangażowania / Liczba MD / Stawka / PLN/MD netto /
    Lokalizacja / Numer SSGW
    Andrzej Iciek / Projektant / UI/UX Senior / 2026-09-01 / 2026-11-30 / 64 / 900,00 / …
    Łączna wartość zamówienia wynosi: 57 600,00 PLN netto …

Wiersz osoby: nazwisko, potem profil (1–2 linie), potem DWIE daty ISO, liczba MD
i stawka. Parsujemy fail-closed: wiersz bez kompletu dwóch dat i dwóch liczb
nie jest wierszem.
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
_HEADER_END_RE = re.compile(r"Numer\s+SSGW", re.IGNORECASE)
_TABLE_END_RE = re.compile(r"[ŁL][aą]czna\s+warto[śs][ćc]", re.IGNORECASE)
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_NUMBER_RE = re.compile(r"^\d[\d\s  .]*(?:,\d{1,2})?$")
_NAME_RE = re.compile(r"^[^\d]{3,80}$")


def order_number(text: str) -> Optional[str]:
    return labelled_text(ORDER_NUMBER_LABEL, text)


_ROW_LINE_RE = re.compile(
    r"^(?P<name>[^\d\n]{3,80}?)[ \t]+(?P<start>\d{4}-\d{2}-\d{2})[ \t]+(?P<end>\d{4}-\d{2}-\d{2})"
    r"[ \t]+(?P<md>\d[\d  ]*)[ \t]+(?P<rate>\d[\d  .]*,\d{2})\b",
    re.MULTILINE,
)


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    """Wiersze Wykonawców z tabeli (deterministycznie, fail-closed).

    Dwa układy tej samej tabeli, zależne od ekstraktora tekstu: pdfplumber
    (produkcja) oddaje WIERSZ w jednej linii — „Andrzej Iciek 2026-09-01
    2026-11-30 64 900,00 Warszawa 103587-1"; inne ekstraktory oddają komórki
    po jednej na linię. Obsługujemy oba: najpierw wiersz-w-linii, potem
    komórka-na-linię.
    """
    text = text or ""
    rows: list[ConsultantOrderRow] = []
    for m in _ROW_LINE_RE.finditer(text):
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
    if rows:
        return rows
    return _extract_rows_cell_per_line(text)


def _extract_rows_cell_per_line(text: str) -> list[ConsultantOrderRow]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    start = next((i for i, ln in enumerate(lines) if _HEADER_END_RE.search(ln)), None)
    if start is None:
        return []
    rows: list[ConsultantOrderRow] = []
    i = start + 1
    while i < len(lines) and not _TABLE_END_RE.search(lines[i]):
        name_line = lines[i]
        if not _NAME_RE.match(name_line):
            i += 1
            continue
        dates: list[str] = []
        numbers: list[Decimal] = []
        j = i + 1
        while j < len(lines) and not _TABLE_END_RE.search(lines[j]) and j < i + 12:
            ln = lines[j]
            if _ISO_RE.match(ln):
                dates.append(ln)
            elif _NUMBER_RE.match(ln):
                amount = normalize_amount(ln)
                if amount is not None:
                    numbers.append(amount)
            if len(dates) >= 2 and len(numbers) >= 2:
                break
            j += 1
        if len(dates) >= 2 and len(numbers) >= 2:
            rows.append(
                ConsultantOrderRow(
                    consultant_name=clean_person_name(name_line),
                    start_date=normalize_date(dates[0], end=False),
                    end_date=normalize_date(dates[1], end=True),
                    md_total=numbers[0],
                    rate_client=numbers[1],
                    rate_unit="day",
                    uncertain=False,
                )
            )
            i = j + 1
        else:
            i += 1
    return rows


def apply_pko_bp_order_policy(
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
    if len(rows) == 1:
        row = rows[0]
        set_field(result, "start_date", row.start_date)
        set_field(result, "end_date", row.end_date)
        set_field(result, "rate_client", row.rate_client)
        set_field(result, "rate_unit", "day")
        set_field(result, "md_total", row.md_total)
    elif rows:
        # Wiele osób: pola dokumentu nie znaczą nic — okres i stawka są per wiersz.
        for name in ("rate_client", "rate_unit", "md_total"):
            clear_field(result, name)
    if rows and not result.consultant_rows:
        result.consultant_rows = rows

    reasons: list[str] = []
    if result.title is None:
        reasons.append("Nie znaleziono pola „Zamówienie nr” — sprawdź numer zamówienia")
    if not rows:
        reasons.append(
            "Nie rozpoznano tabeli Wykonawców (okres, MD, stawka) — wpisz ręcznie"
        )
    result.uncertain_reasons = reasons
    result.uncertain = bool(reasons)
    return result
