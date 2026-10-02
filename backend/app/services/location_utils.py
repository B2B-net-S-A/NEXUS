"""Shared location parsing/matching for candidate↔job matching.

Both ``candidate.location`` and ``job.location`` appear in two shapes in
production:

  • plain text — ``"Warszawa"``, ``"Kraków / remote"``
  • the structured JSON blob Traffit/TalentRadar imports store verbatim:
    ``{"locality":"Warszawa","region1":"Mazowieckie","country":"Polska",...}``

8 242 of 8 305 located candidates are the blob shape (the structured
``city``/``region`` columns were never backfilled), so ``location`` is the only
usable source and parsing the blob is mandatory — a raw-string substring
compare against the blob practically never matches.

Extracted from ``app.api.matching`` (PR #424) so the legacy ``/ai-matches``
engine, the hybrid ``/recommendations`` engine and the composite
``scoring_service._score_location`` layer all share one implementation.
"""

from __future__ import annotations

import json
import re

# Place keys read out of the structured blob, in rough specificity order.
# Coordinates / postcode are intentionally excluded — they are not place names.
_BLOB_PLACE_KEYS = ("locality", "city", "region1", "region2", "region3", "country")

# Plain-text location separators ("Kraków / remote", "Gdańsk, Pomorskie") —
# także słowa alternatywy: "Gdansk or Warsaw", "Warszawa lub Kraków" (lustro
# `CITY_ALTERNATIVE` z `frontend/src/lib/job-search-prefill.ts`). Do 27.09.2026
# "Gdansk or Warsaw" był jednym tokenem i bramka biura ukrywała każdego.
_TEXT_SEPARATORS = re.compile(
    r"[,/;|]+|\s+(?:lub|albo|oraz|or|and|i)\s+", re.IGNORECASE
)
# „Warszawa (hybrydowo)”, „okolice Krakowa” — dopisek to nie miasto.
_PARENTHESES = re.compile(r"\([^)]*\)")
_NEAR_PREFIX = re.compile(r"^(?:okolice|okolic|near|around)\s+", re.IGNORECASE)


def location_tokens(raw: object) -> set[str]:
    """Normalized lowercase place tokens from a location value (blob or text).

    Returns the set of meaningful place tokens (locality, regions, country);
    an empty set when nothing usable is present. A blob that fails to parse
    yields an empty set rather than leaking the raw JSON string in as a junk
    plaintext token.
    """
    if not raw:
        return set()
    s = str(raw).strip()
    if not s:
        return set()
    tokens: set[str] = set()
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except (ValueError, TypeError):
            return set()
        if isinstance(data, dict):
            for key in _BLOB_PLACE_KEYS:
                v = data.get(key)
                if isinstance(v, str) and v.strip():
                    tokens.add(v.strip().lower())
        return tokens
    for part in _TEXT_SEPARATORS.split(_PARENTHESES.sub(" ", s.lower())):
        part = _NEAR_PREFIX.sub("", part.strip()).strip()
        if part:
            tokens.add(part)
    return tokens


# ── Tokeny MIASTA (SCV-02) ───────────────────────────────────────────────────
#
# Połowa „miasto” w scoringu (`scoring_service._score_location`) liczyła pełne
# punkty za DOWOLNY wspólny token, a blob importu niesie kraj i województwo —
# „Warszawa, Polska” i „Kraków, Polska” dopasowywały się przez „polska”. Pełna
# połowa należy się WYŁĄCZNIE za wspólne miasto; kraj ani region nie są
# dowodem, że kandydat dojedzie do biura.

_BLOB_CITY_KEYS = ("locality", "city")

_REGION_TOKENS = frozenset(
    {
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
    }
)

_COUNTRY_TOKENS = frozenset(
    {
        "polska",
        "poland",
        "pl",
        "rzeczpospolita polska",
        "niemcy",
        "germany",
        "ukraina",
        "ukraine",
        "europe",
        "europa",
        "eu",
        "uk",
        "united kingdom",
        "wielka brytania",
    }
)

_NOT_A_CITY = frozenset(
    {"remote", "zdalnie", "zdalna", "zdalny", "hybrid", "hybrydowo", "onsite"}
)

_REGION_PREFIX = re.compile(r"^(województwo|woj\.?)\s+")


def _is_city_token(token: str) -> bool:
    t = _REGION_PREFIX.sub("", token.strip().lower())
    if not t or t != token.strip().lower():
        # Miał prefiks „województwo …” — to region, nie miasto.
        return False
    return t not in _REGION_TOKENS and t not in _COUNTRY_TOKENS and t not in _NOT_A_CITY


def is_country_only(raw: object) -> bool:
    """Czy wartość to sam kraj („PL”, „Polska”) — w polu miasta to brak miasta."""
    tokens = location_tokens(raw)
    return bool(tokens) and all(t in _COUNTRY_TOKENS for t in tokens)


def city_tokens(raw: object) -> set[str]:
    """Tokeny miasta z lokalizacji (blob albo tekst) — bez kraju i regionu.

    Blob: wyłącznie ``locality``/``city``. Tekst: tokeny `location_tokens`
    minus kraje, województwa i tryby pracy. Pusty zbiór = miasto nieznane.
    """
    if not raw:
        return set()
    s = str(raw).strip()
    if s.startswith("{"):
        try:
            data = json.loads(s)
        except (ValueError, TypeError):
            return set()
        if not isinstance(data, dict):
            return set()
        return {
            v.strip().lower()
            for key in _BLOB_CITY_KEYS
            if isinstance((v := data.get(key)), str) and v.strip()
        }
    return {t for t in location_tokens(s) if _is_city_token(t)}


# Trójmiasto to trzy miasta, a słownik miejscowości wskazuje nim tylko Gdańsk.
_TRICITY_NAMES = ("gdansk", "gdynia", "sopot")
_TRICITY_KEYS = frozenset({"trojmiasto", "tricity"})


def place_keys(token: str) -> frozenset[str]:
    """Klucze porównania miejsca: id ze słownika (``pl_places`` — aliasy
    „Warsaw”, „Cracow”, bez polskich znaków) albo sam klucz nazwy.

    „Warsaw” i „Warszawa” dają ten sam klucz, „Gdansk” i „Gdańsk” też; do
    27.09.2026 bramka biura porównywała surowe napisy i ukrywała kandydatów
    z Warszawy w rekrutacji zapisanej jako „Warsaw”.
    """
    from app.services import pl_places

    key = pl_places.place_key(token)
    if not key:
        return frozenset()
    if key in _TRICITY_KEYS:
        return frozenset(
            f"id:{place.id}"
            for name in _TRICITY_NAMES
            if (place := pl_places.resolve(name)) is not None
        )
    place = pl_places.resolve(key)
    return frozenset({f"id:{place.id}" if place is not None else f"k:{key}"})


def tokens_overlap(a: set[str], b: set[str]) -> bool:
    """Overlap between two token sets: same place, or substring (either way).

    ``"warszawa"`` matches ``"warszawa, mazowieckie"``, ``"warsaw"`` and
    ``"Warszawa"``; ``"gdansk"`` matches ``"gdańsk"``. Empty on either side →
    no overlap.
    """
    if not a or not b:
        return False
    for x in a:
        for y in b:
            if x == y or x in y or y in x:
                return True
    keys_a = frozenset().union(*(place_keys(x) for x in a))
    keys_b = frozenset().union(*(place_keys(y) for y in b))
    if keys_a & keys_b:
        return True
    # Odmiana bez polskich znaków: „krakowa” ⊃ „krakow”, „gdanska” ⊃ „gdansk”.
    from app.services.pl_places import place_key

    folded_a = {place_key(x) for x in a}
    folded_b = {place_key(y) for y in b}
    return any(
        len(x) >= 4 and len(y) >= 4 and (x.startswith(y) or y.startswith(x))
        for x in folded_a
        for y in folded_b
    )


def location_matches(requested_tokens: set[str], candidate_location: object) -> bool:
    """True if a candidate's location is compatible with the requested tokens.

    No request tokens → no filter (everyone passes). A candidate with no
    parseable location is excluded under an active filter (standard search
    semantics, mirroring the manual-search ``location_cities`` behaviour).
    """
    if not requested_tokens:
        return True
    cand_tokens = location_tokens(candidate_location)
    if not cand_tokens:
        return False
    return tokens_overlap(requested_tokens, cand_tokens)


# ── Źródła lokalizacji kandydata (switch „skąd brać miasto", runda 3) ────────
#
# CV-side: kolumny `location` (blob/tekst) + `city` (backfill Fali 3, ~81%).
# Notes-side: fakty potwierdzone w rozmowach — `preferences.locations[]`
# oraz `relocation.targets[]` (te drugie tylko, gdy `willing` nie jest False:
# kierunek relokacji, na który kandydat się NIE godzi, nie jest jego
# lokalizacją). Dostęp przez jawne isinstance — `cv_extracted_data` na prodzie
# bywa listą (repo-wide guard-test zakazuje idiomu `or {}`).

LOCATION_SOURCES = ("all", "cv", "notes")


def _notes_insights_dict(candidate) -> dict | None:
    data = getattr(candidate, "cv_extracted_data", None)
    if not isinstance(data, dict):
        return None
    ins = data.get("_notes_insights")
    return ins if isinstance(ins, dict) else None


def candidate_location_tokens(candidate, source: str = "all") -> set[str]:
    """Tokeny miejsc kandydata z wybranego źródła (``all``/``cv``/``notes``).

    Ludzkie ``preferences.office_cities`` (0278, modal edycji kandydata) żyją
    w kubełku ``cv``/``all`` obok `location`/`city` — to też fakt WPISANY
    przez człowieka, nie wywiedziony przez AI. Gdy są niepuste, w kubełku
    ``all`` PRZESŁANIAJĄ notatkowe ``_notes_insights.preferences.locations``:
    człowiek nadpisuje to, co AI wyczytało z rozmowy. ``relocation.targets``
    dokłada się zawsze, niezależnie od `office_cities` — to inny fakt (dokąd
    kandydat CHCE się przeprowadzić), nie preferencja biura. Wywołanie z
    `source="notes"` w izolacji zostaje czysto-AI: `office_cities` nigdy nie
    jest tam czytane, więc nic go tam nie może przesłonić.
    """
    tokens: set[str] = set()
    office_city_tokens: set[str] = set()
    if source in ("all", "cv"):
        tokens |= location_tokens(getattr(candidate, "location", None))
        tokens |= location_tokens(getattr(candidate, "city", None))
        prefs = getattr(candidate, "preferences", None)
        if isinstance(prefs, dict):
            office_cities = prefs.get("office_cities")
            if isinstance(office_cities, list):
                for item in office_cities:
                    if isinstance(item, str):
                        office_city_tokens |= location_tokens(item)
        tokens |= office_city_tokens
    if source in ("all", "notes"):
        ins = _notes_insights_dict(candidate)
        if ins is not None:
            notes_prefs = ins.get("preferences")
            if isinstance(notes_prefs, dict) and not office_city_tokens:
                locs = notes_prefs.get("locations")
                if isinstance(locs, list):
                    for item in locs:
                        if isinstance(item, str):
                            tokens |= location_tokens(item)
            reloc = ins.get("relocation")
            if isinstance(reloc, dict) and reloc.get("willing") is not False:
                targets = reloc.get("targets")
                if isinstance(targets, list):
                    for item in targets:
                        if isinstance(item, str):
                            tokens |= location_tokens(item)
    return tokens


# Tokeny, które NIE są nazwami miejsc, więc nie mogą liczyć się jako „biuro
# kandydata" — bez tego odsiania kandydat z jedyną deklaracją „zdalnie"/„remote"
# miałby niepusty zbiór tokenów biurowych i był ukrywany na KAŻDEJ ofercie
# biurowej (dokładna odwrotność tego, co ta deklaracja mówi). Same regiony
# (np. „Mazowieckie" bez miasta) ZOSTAJĄ tokenami biura — znane ograniczenie:
# region jest realnym miejscem, tylko mniej precyzyjnym niż miasto.
_NON_PLACE_TOKENS = frozenset(
    {
        "polska",
        "poland",
        "pl",
        "remote",
        "zdalnie",
        "zdalna",
        "zdalny",
        "hybrid",
        "hybrydowo",
    }
)


def candidate_office_tokens(candidate) -> set[str]:
    """Tokeny miejsc, w których kandydat gotów jest bywać w biurze.

    `candidate_location_tokens(candidate, "all")` minus tokeny, które nie są
    nazwami miejsc (patrz `_NON_PLACE_TOKENS`) — dealbreaker dni/miasta biura
    (`dealbreaker_filters.office_city_mismatch`) porównuje WYŁĄCZNIE to.
    """
    return candidate_location_tokens(candidate, "all") - _NON_PLACE_TOKENS
