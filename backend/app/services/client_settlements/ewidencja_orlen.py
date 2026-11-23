"""Ewidencja czasu pracy Orlenu w PDF (wydruk arkusza BL/B2B). Bez bazy.

Inny wzór niż protokół rozliczenia (``protocol_orlen``): tabela „Forma umowy ·
Przełożony · NAZWISKO I IMIĘ · Data [RRRR-MM-DD] · Kategoria · Podkategoria ·
Procent dnia · Nr zadania / MPK · … · Ilość godzin”, wiersz na dzień:
„BL <przełożony> <osoba> 2026-10-01, czwartek <kategoria> 100,00% MPK 1234 8,0”.
Weekend to sama data. Obok tabeli bywa tabela przestawna z „Suma końcowa 176”.

Godziny = suma „Ilość godzin” z wierszy dni; MD = godziny / ``fields.md_hours``
(``declared.evaluate``). Bez MD (godziny ``None``, dzieli człowiek), gdy:
- „Suma końcowa” jest inna niż suma wierszy,
- wiersz dnia z godzinami mówi o urlopie, zwolnieniu, święcie, odbiorze,
  nadgodzinach albo dyżurze (te godziny nie są zwykłymi MD; taki wiersz z 0 h
  pomijamy),
- w wierszu dnia nie ma liczby godzin.
Wiersze kilku różnych osób albo dni z kilku miesięcy = ``None``.

Przełożonego od osoby nie da się oddzielić (oba to „Nazwisko Imię”), więc
nazwiskiem z dokumentu jest cały odcinek między formą umowy a datą; kontrola
imienia i nazwiska sprawdza, czy osoba z kontraktu w nim jest.
"""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Optional

from app.services.client_settlements.declared import (
    PDF,
    Declared,
    number,
    pdf_text,
    short_lines,
)

SOURCE = "Ewidencja czasu Orlen"
_MARKERS = (
    re.compile(r"procent\s+dnia", re.I),
    re.compile(r"nazwisko\s+i\s+imi", re.I),
)
_WEEKDAY = r"(?:poniedziałek|wtorek|środa|czwartek|piątek|sobota|niedziela)"
_DAY = re.compile(r"(\d{4})-(\d{2})-(\d{2}),\s*" + _WEEKDAY + r"\b(.*)$", re.I)
_FORM = re.compile(r"^(?:BL|B2B)\s+(.+?)\s+$", re.I)
# Po „100,00%” pierwsza liczba z przecinkiem to „Ilość godzin” („MPK 1234” jej nie ma).
_HOURS = re.compile(r"\d{1,3}[,.]\d{2}\s*%.*?(?<![\d,.])(\d{1,2}[,.]\d{1,2})(?![\d%])")
_ABSENCE = re.compile(
    r"urlop|zwolnien|nieobecn|święt|swiet|odbi[oó]r|nadgodz|dyżur|dyzur", re.I
)
_TOTAL = re.compile(r"suma\s+końcowa\s+(\d+(?:[,.]\d+)?)", re.I)


def parse_text(text: str) -> Optional[Declared]:
    text = short_lines(text)
    if not all(marker.search(text) for marker in _MARKERS):
        return None
    hours = Decimal("0")
    readable = True
    months: Counter[str] = Counter()
    people: set[str] = set()
    for line in text.splitlines():
        day = _DAY.search(line)
        if day is None:
            continue
        months[f"{day.group(1)}-{day.group(2)}"] += 1
        form = _FORM.match(line[: day.start()])
        if form is None:
            continue  # weekend albo dzień bez wpisu
        people.add(" ".join(form.group(1).split()))
        rest = day.group(4)
        found = _HOURS.search(rest)
        value = (number(found.group(1)) or Decimal("0")) if found else None
        absence = _ABSENCE.search(rest) is not None
        if (absence and not value) or value == 0:
            continue  # święto albo urlop z 0 h nie zmienia sumy
        if absence or value is None:
            readable = False
            continue
        hours += value
    if not people or len(people) > 1 or len(months) != 1:
        return None
    total = _TOTAL.search(text)
    if total is not None and number(total.group(1)) != hours:
        readable = False
    return Declared(
        source=SOURCE,
        consultant=next(iter(people)),
        month=next(iter(months)),
        hours=hours if readable and hours > 0 else None,
    )


def parse(content: bytes, mime: str) -> Optional[Declared]:
    if mime != PDF:
        return None
    text = pdf_text(content)
    return parse_text(text) if text else None
