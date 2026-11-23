"""Potwierdzenie godzin ERGO („Monthly confirmation of hours worked”) w PDF. Bez bazy.

Wzór klienta ERGO Technology: „Month (mm/yyyy)” i nazwisko konsultanta pod
nagłówkiem (miesiąc jako „01-09-2026” albo „September 2026”), tabela projektów
z godzinami, wiersz „Total 168,00” (w nowszym wzorze „Total 176,00 22,00”:
godziny i PD). MD = godziny z „Total” / ``fields.md_hours``.

Plik spoza wzoru daje ``None``: wtedy MD wpisują Finanse.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services.client_settlements.declared import (
    PDF,
    Declared,
    month_in,
    number,
    pdf_text,
)

SOURCE = "Potwierdzenie godzin ERGO"
_TITLE = re.compile(r"monthly\s+confirmation\s+of\s+hours\s+worked", re.I)
_MONTH_LABEL = re.compile(r"month\s*\(mm/yyyy\)(.*)", re.I)
_NAME_LABEL = re.compile(r"(?:external\s+)?consultant\s+name", re.I)
_MONTH_VALUE = re.compile(
    r"^\s*(\d{1,2}[-./]\d{1,2}[-./]20\d{2}|\d{1,2}[-./]20\d{2}|[a-z]+\s+20\d{2})\s*(.*)$",
    re.I,
)
_TOTAL = re.compile(r"^\s*total\s+(\d[\d ]*(?:[.,]\d+)?)", re.I | re.M)


def parse_text(text: str) -> Optional[Declared]:
    if not _TITLE.search(text):
        return None
    lines = text.splitlines()
    month: Optional[str] = None
    consultant: Optional[str] = None
    for index, line in enumerate(lines):
        label = _MONTH_LABEL.search(line)
        if not label:
            continue
        rest = _NAME_LABEL.sub("", label.group(1)).strip()
        if not rest and index + 1 < len(lines):
            rest = lines[index + 1].strip()
        value = _MONTH_VALUE.match(rest)
        if value:
            month = month_in(value.group(1))
            consultant = value.group(2).strip() or None
        break
    total = _TOTAL.search(text)
    return Declared(
        source=SOURCE,
        consultant=consultant,
        month=month,
        hours=number(total.group(1)) if total else None,
    )


def parse(content: bytes, mime: str) -> Optional[Declared]:
    if mime != PDF:
        return None
    text = pdf_text(content)
    return parse_text(text) if text else None
