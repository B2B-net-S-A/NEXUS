"""Protokół rozliczenia Orlenu (DOCX albo PDF) z liczbą godzin. Bez bazy.

Protokół do zamówienia z umowy ramowej: „OKRES ROZLICZENIOWY: WRZESIEŃ 2026”,
osoba ze stawką („Jan Testowy (150zł x8h = 1200zł MD)”), „Faktyczny wymiar
Roboczodni” („22 MD - po 6h”) i „Sugerowane wynagrodzenie”. Wynagrodzenie bywa
liczone od godzin („132 h x 150 PLN = 19 800 PLN”) albo od MD
(„22 x 1200 PLN = 26 400 PLN”); bez „h” i „MD” rozstrzyga stawka z protokołu
(godzinowa albo za MD).

Faktury Finansów liczą MD z godzin (132 h = 16,5 MD, nie 22 dni po 6 h), więc
MD = godziny / ``fields.md_hours``, a przy wynagrodzeniu od MD — liczba MD.
Bez wynagrodzenia w protokole godziny z „Faktycznego wymiaru”. Kilka różnych kwot (kilka
osób w protokole) nie daje MD: dzieli człowiek.

Plik spoza wzoru daje ``None``: wtedy MD wpisują Finanse.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from app.services.client_settlements.declared import (
    DOCX,
    PDF,
    Declared,
    docx_text,
    month_in,
    number,
    pdf_text,
)

SOURCE = "Protokół Orlen"
TOLERANCE = Decimal("1")
_NUM = r"\d+(?:[.,]\d+)?"
_AMOUNT = r"\d[\d \xa0]*(?:[.,]\d+)?"
_CURRENCY = r"(?:zł|pln)"
_PERIOD = re.compile(r"okres\s+rozliczeniowy\s*:?\s*([^|\n]*)", re.I)
_WORKDAYS = re.compile(r"roboczod|sugerowane\s+wynagrodzenie", re.I)
_NAME = r"([A-ZĄĆĘŁŃÓŚŹŻ][\w-]+(?:[ \t]+[A-ZĄĆĘŁŃÓŚŹŻ][\w-]+)+)"
# „Jan Testowy (150zł x8h …” albo w DOCX „… za Roboczodzień | Jan Testowy”.
_PERSON = re.compile(_NAME + r"\s*\(\s*\d")
_PERSON_CELL = re.compile(r"roboczodzie[nń]\s*\|\s*" + _NAME, re.I)
# „150zł x8h = 1200zł MD”, „175 pln x 8= 1400 PLN/MD”
_RATE_PAIR = re.compile(
    r"("
    + _NUM
    + r")\s*"
    + _CURRENCY
    + r"\s*[x×]\s*8\s*h?\s*=\s*("
    + _AMOUNT
    + r")\s*"
    + _CURRENCY,
    re.I,
)
_RATE_HOUR = re.compile(r"(" + _NUM + r")\s*" + _CURRENCY + r"\s*/\s*h(?![a-z])", re.I)
_RATE_MD = re.compile(
    r"(" + _AMOUNT + r")\s*" + _CURRENCY + r"\s*(?:/\s*MD|\(\s*MD\s*\))", re.I
)
_PAYMENT = re.compile(
    r"(?<![\d.,])("
    + _NUM
    + r")\s*(h|md)?\s*[x×]\s*("
    + _AMOUNT
    + r")\s*"
    + _CURRENCY
    + r"\s*=\s*("
    + _AMOUNT
    + r")\s*"
    + _CURRENCY,
    re.I,
)
_WORKDAY_HOURS = re.compile(
    r"(" + _NUM + r")\s*MD\s*[-–]\s*po\s*(" + _NUM + r")\s*h", re.I
)


def _rates(text: str) -> tuple[set[Decimal], set[Decimal]]:
    hourly: set[Decimal] = set()
    per_md: set[Decimal] = set()
    for found in _RATE_PAIR.finditer(text):
        hourly.add(number(found.group(1)) or Decimal("0"))
        per_md.add(number(found.group(2)) or Decimal("0"))
    hourly |= {number(m.group(1)) or Decimal("0") for m in _RATE_HOUR.finditer(text)}
    per_md |= {number(m.group(1)) or Decimal("0") for m in _RATE_MD.finditer(text)}
    return hourly - {Decimal("0")}, per_md - {Decimal("0")}


def _near(value: Decimal, options: set[Decimal]) -> bool:
    return any(abs(value - option) <= TOLERANCE for option in options)


def _payment(
    text: str,
) -> tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """(godziny, MD, kwota) z „Sugerowanego wynagrodzenia”; ``None`` bez jednej kwoty."""

    hourly, per_md = _rates(text)
    by_amount: dict[Decimal, dict[str, Decimal]] = {}
    for found in _PAYMENT.finditer(text):
        count = number(found.group(1))
        rate = number(found.group(3))
        amount = number(found.group(4))
        if count is None or rate is None or amount is None:
            continue
        unit = (found.group(2) or "").lower()
        if not unit:
            if _near(rate, per_md):
                unit = "md"
            elif _near(rate, hourly):
                unit = "h"
            else:
                continue
        by_amount.setdefault(amount, {}).setdefault(unit, count)
    if len(by_amount) != 1:
        return None, None, None
    amount, units = next(iter(by_amount.items()))
    if "h" in units:
        return units["h"], None, amount
    return None, units["md"], amount


def parse_text(text: str) -> Optional[Declared]:
    period = _PERIOD.search(text)
    if not period or not _WORKDAYS.search(text):
        return None
    hours, md, amount = _payment(text)
    if hours is None and md is None and not _PAYMENT.search(text):
        # Bez wynagrodzenia w protokole. Wynagrodzenie, którego nie da się
        # rozstrzygnąć (kilka osób, nieznana stawka), nie ma tu zamiennika.
        workdays = [
            (number(m.group(1)) or Decimal("0")) * (number(m.group(2)) or Decimal("0"))
            for m in _WORKDAY_HOURS.finditer(text)
        ]
        hours = sum(workdays, Decimal("0")) if workdays else None
    person = _PERSON.search(text) or _PERSON_CELL.search(text)
    return Declared(
        source=SOURCE,
        consultant=person.group(1) if person else None,
        month=month_in(period.group(1)),
        hours=hours,
        md=md,
        amount=amount,
    )


def parse(content: bytes, mime: str) -> Optional[Declared]:
    if mime == PDF:
        text = pdf_text(content)
    elif mime == DOCX:
        text = docx_text(content)
    else:
        return None
    return parse_text(text) if text else None
