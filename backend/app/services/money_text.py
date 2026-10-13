"""Kwoty, stawki i dostępność w wolnym tekście notatek.

Jeden wzorzec kwoty dla QC CV (poprawki AI, edytor) i dla materiału, który
idzie do modelu generatora CV. Notatka „150 PLN/h + VAT, dostępny 06.03.2023”
nie jest treścią CV: stawka to ustalenie handlowe, a dostępność widzi klient
tylko z profilu (audyt 13.10.2026: taka notatka szła do promptu generatora).
"""

from __future__ import annotations

import re

RATE_WORD_RE = re.compile(r"stawk|\brate\b|wynagrodz|salary|zarobk", re.IGNORECASE)

# Kwota pieniędzy, ściślej niż luźne „liczba + waluta”, które bierze
# „3 europejskich” i „5 złożonych” za euro i złote.
MONEY_RE = re.compile(
    r"\d[\d\s.,]*\s*(?:(?:tys|mln)\b\.?\s*|k\s*)?(?:zł|zl|pln|euro|eur|usd|€|\$)(?!\w)"
    r"(?:\s*/\s*(?:h|godz|md|dzie[nń]|mies)\w*)?"
    r"|[€$]\s*\d[\d\s.,]*\d|[€$]\s*\d"
    r"|\d[\d\s.,]*\s*/\s*(?:h|godz|md)\b",
    re.IGNORECASE,
)

# Kwota za czas pracy („150 PLN/h”, „1200 zł/md”, „160/h”) — to zawsze stawka,
# także bez słowa „stawka” obok.
_PER_TIME_RE = re.compile(r"/\s*(?:h|godz|md|dzie[nń]|mies)", re.IGNORECASE)

# Dostępność kandydata, nie systemu: „dostępny od…”, „dostępna 06.03.2023”,
# „okres wypowiedzenia”. „Dostępność systemu 99,9%” zostaje.
_AVAILABILITY_RE = re.compile(
    r"\bdostępn[aey]\s+(?:od|w|na|\d|zaraz|natychmiast)"
    r"|\bdostępność\s*:"
    r"|\bokres\w*\s+wypowiedzeni\w*"
    r"|\bavailable\s+(?:from|in|now|immediately)"
    r"|\bavailability\s*:"
    r"|\bnotice\s+period",
    re.IGNORECASE,
)

# Granice fragmentu: przecinek albo średnik ze spacją, kropka kończąca zdanie,
# nowa linia. „1,5 roku” i „06.03.2023” nie są granicą.
_SEGMENT_END_RE = re.compile(r"(?<=[,;])\s+|(?<=\.)\s+(?=[A-ZĄĆĘŁŃÓŚŹŻ\d])|\n")


def is_rate_text(text: str) -> bool:
    """Czy fragment mówi o stawce: kwota za czas albo kwota przy słowie „stawka”."""
    for match in MONEY_RE.finditer(text or ""):
        if _PER_TIME_RE.search(match.group()) or RATE_WORD_RE.search(text):
            return True
    return False


def strip_rates_and_availability(text: str | None) -> str:
    """Tekst bez fragmentów o stawce i dostępności kandydata.

    Usuwa cały fragment (do przecinka, średnika, końca zdania albo linii), bo
    sama kwota bez niego zostawiałaby „+ VAT, B2B” albo datę bez kontekstu.
    """
    if not text:
        return ""
    lines: list[str] = []
    for line in text.split("\n"):
        kept = [
            part
            for part in _SEGMENT_END_RE.split(line)
            if part.strip()
            and not is_rate_text(part)
            and not _AVAILABILITY_RE.search(part)
        ]
        joined = " ".join(p.strip() for p in kept).strip()
        if joined or not line.strip():
            lines.append(joined)
    return "\n".join(lines).strip()
