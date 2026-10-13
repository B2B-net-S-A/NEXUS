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

_MONTH = (
    r"(?:stycz|lut|mar|kwie|maj|czerw|lip|sierp|wrze|paźdz|pazdz|listop|grud"
    r"|jan|feb|apr|may|jun|jul|aug|sep|oct|nov|dec)"
)
# Dostępność kandydata, nie systemu: „Kandydat dostępny od 1.11”, „dostępna
# 06.03.2023”, „od zaraz”, „1 miesiąc wypowiedzenia”. „API dostępne w chmurze”,
# „aplikacja dostępna na iOS” i „dostępność systemu 99,9%” zostają.
_AVAILABILITY_RE = re.compile(
    r"\b(?:jest|będzie|bedzie|byłby|byłaby|kandydat\w*|pan|pani|on|ona)\s+dostępn"
    r"|\bdostępn\w*\s+(?:od\s+(?:zaraz|razu|ręki|jutra|teraz|now|\d|początk"
    r"|poniedział|przyszł|nowego|" + _MONTH + r")|zaraz|natychmiast|\d"
    r"|w\s+ciągu|po\s+(?:okresie|wypowiedz|zakończ))"
    r"|\bdostępność\s*:"
    r"|\bwypowiedzeni\w*"
    r"|\bavailable\s+(?:from\s+(?:\d|now|" + _MONTH + r")|immediately|now"
    r"|in\s+\d|within)"
    r"|\b(?:is|will\s+be|candidate)\s+available"
    r"|\bavailability\s*:"
    r"|\bnotice\s+period",
    re.IGNORECASE,
)

# Pieniądze kandydata w notatce bez słowa „stawka”: „Oczekuje 22k netto”,
# „Ma ofertę za 200 PLN dziennie”. Tylko dla materiału generatora — QC czyta
# ``is_rate_text`` i tej listy nie dostaje.
_CANDIDATE_MONEY_WORD_RE = re.compile(
    r"oczekiw\w*|expectation\w*|\bexpects?\b|\bnetto\b|\bbrutto\b", re.IGNORECASE
)
# Budżet projektu to fakt z CV: „Zarządzał budżetem 2 mln PLN”.
_PROJECT_BUDGET_RE = re.compile(
    r"bud[żz]e(?:t|c)\w*\s+(?:projekt|o\s+warto|\d)|projekt\w*\s+o\s+bud[żz]ec"
    r"|zarządza\w*\s+bud[żz]et|(?:project|managed\s+(?:a\s+)?)\s*budget",
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


def _is_candidate_money(part: str) -> bool:
    if is_rate_text(part):
        return True
    if _PROJECT_BUDGET_RE.search(part):
        return False
    return bool(MONEY_RE.search(part)) or bool(
        re.search(r"\d", part) and _CANDIDATE_MONEY_WORD_RE.search(part)
    )


def strip_rates_and_availability(text: str | None) -> str:
    """Tekst bez fragmentów o pieniądzach i dostępności kandydata.

    W notatce o kandydacie każda kwota (poza budżetem projektu) to ustalenie
    handlowe: stawka, oczekiwania, cudza oferta. Usuwa cały fragment (do
    przecinka, średnika, końca zdania albo linii), bo sama kwota bez niego
    zostawiałaby „+ VAT, B2B” albo datę bez kontekstu.
    """
    if not text:
        return ""
    lines: list[str] = []
    for line in text.split("\n"):
        kept = [
            part
            for part in _SEGMENT_END_RE.split(line)
            if part.strip()
            and not _is_candidate_money(part)
            and not _AVAILABILITY_RE.search(part)
        ]
        joined = " ".join(p.strip() for p in kept).strip()
        if joined or not line.strip():
            lines.append(joined)
    return "\n".join(lines).strip()
