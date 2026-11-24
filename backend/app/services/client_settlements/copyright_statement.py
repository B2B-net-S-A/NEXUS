"""Oświadczenie o przeniesieniu autorskich praw majątkowych (Centrum e-Zdrowia).

CeZ przyjmuje fakturę za miesiąc dopiero z oświadczeniem każdej osoby, osobno
na każdą umowę wykonawczą. Oświadczenie jest na wzorze CeZ, obejmuje okres „od
01.MM.RRRR do 30/31.MM.RRRR” i jest podpisane po końcu miesiąca. W listopadzie
2026 CeZ odrzuciło cztery: podpis 30.10 (przed końcem miesiąca), zły okres oraz
dwa na zmienionym wzorze (logotypy, nagłówek „Wzór”). Przegląd skrzynek Finansów
z 23.11.2026.

Reguła ``cl.copyright_statement`` (uwaga przed fakturą): wśród plików miesiąca
osoby szukamy oświadczenia po nazwie albo treści. Brak oświadczenia, okres inny
niż rozliczany miesiąc, podpis przed jego końcem i nagłówek „Wzór” dają uwagę.
Logotypów nie sprawdzamy, bo tekst PDF ich nie niesie. Bez bazy.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from typing import Iterable, Optional

#: Nazwa pliku: „Oświadczenie … autorskie / prawa / praw majątkowych / CeZ”.
_NAME = re.compile(r"o[sś]wiadcz", re.IGNORECASE)
_NAME_TOPIC = re.compile(r"autor|praw|majatk|cez", re.IGNORECASE)
#: Treść po zdjęciu ogonków.
_CONTENT = re.compile(
    r"(autorskich\s+praw\s+majatkowych|praw\s+autorskich|majatkowych\s+praw\s+autorskich)"
)
_DATE = re.compile(r"(?<!\d)(\d{1,2})[./-](\d{1,2})[./-](20\d{2})(?!\d)")
_PERIOD = re.compile(
    r"od\s*(?:dnia\s*)?(\d{1,2}[./-]\d{1,2}[./-]20\d{2})\s*(?:r\.?)?\s*"
    r"do\s*(?:dnia\s*)?(\d{1,2}[./-]\d{1,2}[./-]20\d{2})"
)
#: Nagłówek wzoru, który CeZ odrzuca w podpisanym oświadczeniu.
_TEMPLATE = re.compile(r"^\s*\(?\s*wz[oó]r\b", re.IGNORECASE | re.MULTILINE)


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", text.replace("ł", "l").replace("Ł", "L"))
    return raw.encode("ascii", "ignore").decode().lower()


def _day(raw: str) -> Optional[date]:
    found = _DATE.search(raw)
    if not found:
        return None
    try:
        return date(int(found.group(3)), int(found.group(2)), int(found.group(1)))
    except ValueError:
        return None


def is_statement(file_name: str, text: Optional[str]) -> bool:
    """Oświadczenie po nazwie pliku albo po treści (nazwa bywa „skan.pdf”)."""

    name = _fold(file_name or "")
    if _NAME.search(name) and _NAME_TOPIC.search(name):
        return True
    return bool(text) and bool(_CONTENT.search(_fold(text)))


@dataclass(frozen=True)
class Statement:
    #: Okres z treści „od … do …”; ``None`` = nie odczytano.
    period: Optional[tuple[date, date]]
    #: Daty w treści poza okresem (miejsce i data podpisu).
    dates: tuple[date, ...]
    template_header: bool


def parse(text: str) -> Statement:
    folded = _fold(text)
    period = None
    found = _PERIOD.search(folded)
    if found:
        start, end = _day(found.group(1)), _day(found.group(2))
        if start and end:
            period = (start, end)
    bounds = set(period or ())
    dates = tuple(
        day
        for match in _DATE.finditer(folded)
        if (day := _day(match.group(0))) is not None and day not in bounds
    )
    return Statement(period, dates, bool(_TEMPLATE.search(text)))


@dataclass(frozen=True)
class Finding:
    state: str
    title: str
    detail: Optional[str] = None


def judge(
    statement: Statement,
    *,
    first: date,
    last: date,
    signed_at: Iterable[datetime] = (),
) -> list[Finding]:
    """Kontrole jednego oświadczenia za miesiąc ``first``–``last``.

    Datę podpisu bierzemy z podpisu elektronicznego PDF, a bez niego z dat
    w treści poza okresem. Data w trakcie miesiąca i żadna po jego końcu =
    podpis przed końcem miesiąca."""

    found: list[Finding] = []
    if statement.period is None:
        found.append(
            Finding(
                "warn", "Oświadczenie bez okresu", "Wzór CeZ: od 01.MM do 30/31.MM."
            )
        )
    elif statement.period != (first, last):
        start, end = statement.period
        found.append(
            Finding(
                "warn",
                "Oświadczenie za inny okres",
                f"W oświadczeniu {start:%d.%m.%Y}–{end:%d.%m.%Y}, rozliczany "
                f"{first:%d.%m.%Y}–{last:%d.%m.%Y}.",
            )
        )
    signed = sorted(moment.date() for moment in signed_at)
    candidates = signed or sorted(d for d in statement.dates if d >= first)
    if candidates and candidates[-1] <= last:
        found.append(
            Finding(
                "warn",
                "Oświadczenie podpisane przed końcem miesiąca",
                f"Podpis {candidates[-1]:%d.%m.%Y}; CeZ przyjmuje podpis po "
                f"{last:%d.%m.%Y}.",
            )
        )
    if statement.template_header:
        found.append(
            Finding(
                "warn",
                "Oświadczenie z nagłówkiem „Wzór”",
                "CeZ odrzuca oświadczenie na zmienionym wzorze: bez nagłówka „Wzór”.",
            )
        )
    if not found:
        found.append(Finding("ok", "Oświadczenie o prawach autorskich za miesiąc"))
    return found
