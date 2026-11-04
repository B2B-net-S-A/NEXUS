"""Bank Pocztowy — warstwa dla układu pdfplumber: okres i osoba.

Ciało polityki (numer „Numer pisma"/„Zamówienie nr", stawka MD→h ze wzoru)
zostaje w parserze. Ta warstwa dokłada to, czego tamta nie czyta::

    Termin rozpoczęcia Planowany termin zakończenia Miejsce świadczenia usług
    10.08.2026 30.09.2026
    …
    Profil Specjalisty (Stanowisko) Imię i nazwisko
    Kierownik projektu Wojciech Sokolnicki

Nagłówek w jednej linii, wartości w następnej. Nazwisko = OSTATNIE dwa tokeny
linii pod nagłówkiem (przed nimi stoi profil, bywa kilkuwyrazowy: „Programista
Power Platform"). Niepewne jest nazwisko, którego dwa ostatnie tokeny nie
wyglądają na imię i nazwisko; trzyczłonowe nazwisko łapie bramka, bo model
czyta osobę niezależnie i jego odczyt musi się zgadzać z tym wierszem.

Stawka wiersza pochodzi ze wzoru „<netto MD>*1,23*<liczba MD>" (ta sama reguła
MD → h co w ciele polityki). Bez stawki bramka uznawała KAŻDY dokument za
niepotwierdzony i nic nie zapisywało się automatem (zgłoszenie 29.09.2026).
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.order_pdf_parser import (
    _bp_hourly_from_md,
    bank_pocztowy_net_md_rate,
)
from app.services.order_policies._shared import (
    ConsultantOrderRow,
    OrderExtraction,
    clean_person_name,
    normalize_date,
    set_field,
)

_PERIOD_HEADER_RE = re.compile(
    r"Termin\s+rozpocz[ęe]cia.*Planowany\s+termin\s+zako[ńn]czenia", re.IGNORECASE
)
_TWO_DATES_RE = re.compile(r"(\d{1,2}\.\d{1,2}\.\d{4})\s+(\d{1,2}\.\d{1,2}\.\d{4})")
_NAME_HEADER_RE = re.compile(r"Imi[ęe]\s+i\s+nazwisko", re.IGNORECASE)
# Imię albo nazwisko: wielka litera, dalej litery; nazwisko dwuczłonowe
# z myślnikiem („Nowak-Kowalska") to jeden token.
_NAME_TOKEN_RE = re.compile(r"[^\W\d_][^\W\d_]+(?:-[^\W\d_][^\W\d_]+)*")


def period(text: str) -> tuple[Optional[str], Optional[str]]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _PERIOD_HEADER_RE.search(ln):
            for nxt in lines[i + 1 : i + 3]:
                m = _TWO_DATES_RE.search(nxt)
                if m:
                    return normalize_date(m.group(1), end=False), normalize_date(
                        m.group(2), end=True
                    )
    return None, None


def consultant_name(text: str) -> tuple[Optional[str], bool]:
    lines = (text or "").splitlines()
    for i, ln in enumerate(lines):
        if _NAME_HEADER_RE.search(ln) and i + 1 < len(lines):
            tokens = lines[i + 1].split()
            if len(tokens) >= 2:
                last_two = tokens[-2:]
                name = clean_person_name(" ".join(last_two))
                name_like = all(
                    _NAME_TOKEN_RE.fullmatch(t) and t[0].isupper() for t in last_two
                )
                return name, not name_like
    return None, True


def extract_rows(text: str) -> list[ConsultantOrderRow]:
    name, uncertain = consultant_name(text)
    if not name:
        return []
    start, end = period(text)
    md_rate = bank_pocztowy_net_md_rate(text)
    return [
        ConsultantOrderRow(
            consultant_name=name,
            rate_client=_bp_hourly_from_md(md_rate) if md_rate else None,
            rate_unit="hour" if md_rate else None,
            start_date=start,
            end_date=end,
            uncertain=uncertain,
        )
    ]


def apply_bank_pocztowy_layout(
    result: OrderExtraction, document_text: str
) -> OrderExtraction:
    start, end = period(document_text)
    if start and end:
        set_field(result, "start_date", start)
        set_field(result, "end_date", end)
        result.uncertain_reasons = [
            r for r in result.uncertain_reasons if "dat okresu" not in r
        ]
    rows = extract_rows(document_text)
    if rows and not result.consultant_rows:
        # Stawka z ciała polityki (wzór) obowiązuje jedną osobę dokumentu.
        rows[0].rate_client = result.rate_client
        rows[0].rate_unit = result.rate_unit
        result.consultant_rows = rows
    result.uncertain = bool(result.uncertain_reasons)
    return result
