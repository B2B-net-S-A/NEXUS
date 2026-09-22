"""Polskie miejscowości: promień w km i województwo w filtrze lokalizacji.

Traffit filtruje „Miejscowość + N km” i „Województwo”. Kandydaci w NEXUSIE nie
mają współrzędnych (``latitude``/``longitude`` puste u 100%), ale 42 tys. ma
wpisane miasto. Dlatego filtr nie liczy odległości w SQL: z pliku
``app/data/pl_places.json`` (GeoNames, CC BY 4.0 — źródło w polu ``_source``)
wybieramy nazwy miejscowości w promieniu i pytamy bazę o kandydatów, których
miasto jest jedną z nich. Plik pokrywa 95% kandydatów z miastem; reszta to
miasta zagraniczne (Berlin, Kyiv…), które i tak nie leżą w polskim promieniu.

Klucz nazwy: bez polskich znaków, małe litery, spacje i myślniki jako jedna
spacja („Jastrzębie-Zdrój” = „jastrzebie zdroj”). To samo wyrażenie liczy SQL
(``place_key_sql``) — oba muszą zostać zgodne.
"""

from __future__ import annotations

import json
import math
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional

from sqlalchemy import func
from sqlalchemy.sql import ColumnElement

_DATA = Path(__file__).resolve().parent.parent / "data" / "pl_places.json"
_FOLD_SRC = "ąćęłńóśźżĄĆĘŁŃÓŚŹŻ"
_FOLD_DST = "acelnoszzACELNOSZZ"
_FOLD_MAP = str.maketrans(_FOLD_SRC, _FOLD_DST)
_SPACES = re.compile(r"[\s\-]+")

VOIVODESHIPS: tuple[str, ...] = (
    "dolnośląskie",
    "kujawsko-pomorskie",
    "lubelskie",
    "lubuskie",
    "łódzkie",
    "małopolskie",
    "mazowieckie",
    "opolskie",
    "podkarpackie",
    "podlaskie",
    "pomorskie",
    "śląskie",
    "świętokrzyskie",
    "warmińsko-mazurskie",
    "wielkopolskie",
    "zachodniopomorskie",
)
MAX_RADIUS_KM = 300


@dataclass(frozen=True)
class Place:
    id: int
    name: str
    voivodeship: str
    lat: float
    lon: float
    population: int


def place_key(value: Optional[str]) -> str:
    """Klucz porównania nazwy (Python) — lustro ``place_key_sql``."""
    head = (value or "").split(",", 1)[0]
    folded = unicodedata.normalize("NFC", head).translate(_FOLD_MAP).lower()
    return _SPACES.sub(" ", folded).strip()


def place_key_sql(expr) -> ColumnElement:
    """Klucz porównania nazwy w SQL: pierwszy człon przed przecinkiem,
    bez polskich znaków, małe litery, myślnik/odstęp = jedna spacja."""
    head = func.split_part(func.coalesce(expr, ""), ",", 1)
    spaced = func.regexp_replace(head, r"[[:space:]-]+", " ", "g")
    return func.btrim(func.lower(func.translate(spaced, _FOLD_SRC, _FOLD_DST)))


@lru_cache(maxsize=1)
def _load() -> tuple[tuple[Place, ...], dict[str, Place]]:
    raw = json.loads(_DATA.read_text(encoding="utf-8"))
    places = tuple(
        Place(id=r[0], name=r[1], voivodeship=r[2], lat=r[3], lon=r[4], population=r[5])
        for r in raw["places"]
    )
    by_key: dict[str, Place] = {}
    # Lista jest posortowana malejąco po liczbie mieszkańców — przy dwóch
    # miejscowościach o tej samej nazwie („Nowa Wieś”) wygrywa większa.
    for place in places:
        by_key.setdefault(place_key(place.name), place)
    by_id = {p.id: p for p in places}
    for alias, place_id in raw.get("aliases", {}).items():
        if place_id in by_id:
            by_key.setdefault(alias, by_id[place_id])
    return places, by_key


def resolve(name: Optional[str]) -> Optional[Place]:
    """Miejscowość po nazwie (bez polskich znaków i wielkości liter) albo ``None``."""
    key = place_key(name)
    return _load()[1].get(key) if key else None


def _distance_km(a: Place, b: Place) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a.lat, a.lon, b.lat, b.lon))
    h = (
        math.sin((lat2 - lat1) / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    )
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def keys_for(place_ids: set[int]) -> list[str]:
    """Wszystkie klucze nazw (także aliasy: „Trójmiasto”, „Warsaw”) wskazanych miejscowości."""
    _, by_key = _load()
    return sorted(k for k, p in by_key.items() if p.id in place_ids)


def keys_within(center: Place, radius_km: float) -> list[str]:
    places, _ = _load()
    ids = {p.id for p in places if _distance_km(center, p) <= radius_km}
    ids.add(center.id)
    return keys_for(ids)


def keys_in_voivodeships(names: list[str]) -> list[str]:
    wanted = {n.strip().lower() for n in names if n and n.strip()}
    places, _ = _load()
    return keys_for({p.id for p in places if p.voivodeship in wanted})


def suggest(prefix: str, limit: int = 8) -> list[Place]:
    """Podpowiedzi do pola miasta: początek nazwy, największe najpierw."""
    key = place_key(prefix)
    if len(key) < 2:
        return []
    places, _ = _load()
    starts = [p for p in places if place_key(p.name).startswith(key)]
    return starts[:limit]
