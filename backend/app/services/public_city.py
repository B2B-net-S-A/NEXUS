"""Miasto do publicznych tekstów: bez ulicy, numeru i kodu pocztowego.

Pole lokalizacji rekrutacji bywa adresem biura klienta („Warszawa, ul.
Kwiatowa 12”, „Siedziba klienta, al. Przykładowa 7, 00-950 Warszawa”). Szło
w całości do ogłoszenia, maila do opiekuna Pracuj.pl, JustJoin.IT i strony
kariery — a po wpisaniu adresu w wyszukiwarkę wiadomo, kto jest klientem
(zgłoszenie 28.10.2026; na stagingu 24 z 204 otwartych rekrutacji).

Lokalizacja bez adresu zostaje bez zmian, także opisowa („Gdańsk lub
Warszawa (2 dni z biura)”). Z adresem zostają same miasta rozpoznane
w słowniku ``pl_places``; bez rozpoznanego miasta — pusto, nie adres.
"""

from __future__ import annotations

import re
from typing import Optional

from app.services import pl_places

_UPPER = "A-ZĄĆĘŁŃÓŚŹŻ"
_POSTAL = re.compile(r"\b\d{2}-\d{3}\b")
_STREET_WORD = re.compile(
    r"(?<![.\w])(?:ul|al|pl|os)\.\s*\S|\b(?:ulic[ayi]|alej[ai]|aleja|plac[u]?|osiedl[ea])\b",
    re.IGNORECASE,
)
# „Warszawa, Kwiatowa 12”: po przecinku nazwa wielką literą i numer domu.
# Wielka litera odróżnia ulicę od „zakładamy 1-2 dni”, a miasto przed
# przecinkiem — od „ASP.NET Core 8, Angular 17”.
_COMMA_STREET = re.compile(
    rf",\s*[{_UPPER}][\w.\-]*(?:\s+[\w.\-]+){{0,3}}\s+\d+[a-zA-Z]?(?:/\d+)?\b"
)
_BEFORE_COMMA = re.compile(r"[,;/(\n]")
_STREET_NUMBER = re.compile(rf"\b[{_UPPER}][\w.\-]*\s+\d+[a-zA-Z]?\b")
_SEGMENTS = re.compile(r"[,;/|()\n]|\s[–—-]\s|\s(?:lub|albo|i|or)\s")


def address_match(text: str) -> Optional[re.Match[str]]:
    """Ulica z numerem albo kod pocztowy — coś, co wskazuje konkretny budynek."""
    found = _POSTAL.search(text) or _STREET_WORD.search(text)
    if found:
        return found
    for match in _COMMA_STREET.finditer(text):
        if pl_places.resolve(_BEFORE_COMMA.split(text[: match.start()])[-1].strip()):
            return match
    return None


def has_address(text: str) -> bool:
    return address_match(text) is not None


def public_city(location: Optional[str]) -> Optional[str]:
    """Miasta z lokalizacji z adresem; lokalizacja bez adresu bez zmian."""
    if not location or not has_address(location):
        return location
    cities: list[str] = []
    for raw in _SEGMENTS.split(location):
        segment = " ".join(_POSTAL.sub(" ", raw).split())
        if (
            not segment
            or _STREET_WORD.search(segment)
            or _STREET_NUMBER.search(segment)
        ):
            continue
        place = pl_places.resolve(segment)
        if place is not None and place.name not in cities:
            cities.append(place.name)
    return " lub ".join(cities)
