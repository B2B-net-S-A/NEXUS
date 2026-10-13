"""Jak system czyta frazę wymagania (13.10.2026) — jedna reguła dla edytora
wierszy, zapisu Profilu Championa i porządków otwartych rekrutacji.

Pomiar na produkcji: 30% pozycji „musi mieć” to zdania, branże, języki
i umiejętności miękkie („doświadczenie w przetargach” ma w CV jedna osoba
z 65 924). Wyszukiwanie szuka słów dosłownie, więc takie frazy nic nie
znajdują, a jako krytyczne ukrywają prawie wszystkich. Decyzja Artura
(wariant A): wymagania dzielą się na „Szukamy po tych słowach” i „Rekruter
sprawdza w rozmowie” (sekcja 4 Championa, `experience`).

``read_phrase`` nie pyta bazy — liczby osób przy podpowiedziach liczy
przeglądarka tym samym zapytaniem co lista kandydatów.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Optional

from app.services import must_gate_terms
from app.services.must_gate_terms import (
    _HEAD_FILLER_WORDS,
    _PAREN_TAIL,
    _clean,
    critical_eligible,
    gate_requirement,
    ignored_reason,
)
from app.services.skill_normalize import strip_version

# Rodzaje frazy. `technology` i `keyword` to słowa do szukania; `prose`,
# `soft` i `language` wymagają decyzji („zamień na słowa” albo „do rozmowy”).
NEEDS_DECISION = frozenset({"prose", "soft", "language", "city"})
# Miasto ≥ 20 tys. mieszkańców — ta sama granica co górne pole listy
# (`api/candidates.py` `_CLASSIFY_CITY_POPULATION`).
CITY_POPULATION = 20_000
MAX_SUGGESTIONS = 5
PHRASE_MAX_CHARS = 500
TALK_ITEM_MAX_CHARS = 160

# Komentarz w nawiasie, który mówi o poziomie albo doświadczeniu — przechodzi
# do rozmowy („SQL — bardzo dobra znajomość”). Inny („narzędzie do testowania
# wydajności”) tylko opisuje technologię i jest pomijany z notką.
_LEVEL_WORDS = re.compile(
    r"znajomo|do[sś]wiadcz|obyci|praktyczn|komercyjn|\bmin\b|\bmin\.|minimum|"
    r"\blat\b|\blata\b|\brok|poziom|zaawansowan|bardzo\s+dobr|dobr[aey]\b|"
    r"biegł|biegl|ekspert|expert|senior|advanced|proficien|hands-on|years?\b|"
    r"experience|knowledge",
    re.IGNORECASE,
)
# Słowa, które nie niosą treści wymagania.
_STOP_WORDS = frozenset(
    {
        "a",
        "and",
        "dla",
        "do",
        "i",
        "in",
        "lat",
        "lata",
        "na",
        "o",
        "od",
        "of",
        "oraz",
        "or",
        "po",
        "pracy",
        "przy",
        "rok",
        "roku",
        "the",
        "w",
        "we",
        "with",
        "years",
        "z",
        "ze",
    }
)
# Końcówki odmiany (od najdłuższej) — rdzeń z gwiazdką łapie wszystkie formy
# („przetargach” → „przetarg*”, „bankowości” → „bankow*”).
_ENDINGS = (
    "ościach",
    "ościami",
    "owych",
    "owymi",
    "ości",
    "ość",
    "ach",
    "ami",
    "owy",
    "owa",
    "owe",
    "ego",
    "emu",
    "ych",
    "ymi",
    "ów",
    "om",
    "em",
    "ie",
    "ej",
    "a",
    "e",
    "i",
    "y",
    "u",
    "ą",
    "ę",
)
_MIN_STEM = 4
_WORD = re.compile(r"[0-9a-ząćęłńóśźż#+.\-/]+", re.IGNORECASE)


@dataclass(frozen=True)
class PhraseReading:
    """Odczyt jednej frazy wiersza wymagań."""

    text: str
    kind: str
    # Słowo do szukania po oczyszczeniu („SQL” z „SQL (bardzo dobra
    # znajomość)”), ``None`` dla frazy, której nie szukamy.
    keyword: Optional[str]
    # Treść nawiasu albo wstęp, gdy są komentarzem.
    comment: Optional[str]
    # Dokąd fraza idzie do rozmowy: ``skills`` / ``domains`` (sekcja 4)
    # albo ``language`` (pole „Język”).
    talk: Optional[str]
    talk_text: Optional[str]
    suggestions: tuple[str, ...]
    needs_decision: bool

    def as_dict(self) -> dict:
        out = asdict(self)
        out["suggestions"] = list(self.suggestions)
        return out


def _cap(text: str) -> str:
    text = " ".join(text.split())
    if len(text) <= TALK_ITEM_MAX_CHARS:
        return text
    cut = text[:TALK_ITEM_MAX_CHARS]
    space = cut.rfind(" ")
    return (cut[:space] if space > TALK_ITEM_MAX_CHARS // 2 else cut).rstrip(" ,;:")


def _stem(word: str) -> Optional[str]:
    lower = word.casefold()
    for ending in _ENDINGS:
        if lower.endswith(ending) and len(lower) - len(ending) >= _MIN_STEM:
            return lower[: -len(ending)] + "*"
    return lower + "*" if len(lower) >= _MIN_STEM + 2 else None


def _dictionary_names_in(text: str) -> list[str]:
    """Nazwy ze słownika stojące w zdaniu („… z wykorzystaniem REST API”)."""
    from app.services.scoring_service import ALIAS_MAP

    words = _WORD.findall(text)
    found: list[str] = []
    seen: set[str] = set()
    i = 0
    while i < len(words):
        for size in (3, 2, 1):
            chunk = " ".join(words[i : i + size])
            key = chunk.casefold().strip(".,")
            if len(words[i : i + size]) == size and key in ALIAS_MAP:
                requirement = gate_requirement(chunk)
                if requirement is not None and key not in seen:
                    seen.add(key)
                    found.append(chunk.strip(".,"))
                i += size
                break
        else:
            i += 1
    return found


def suggestions_for(text: str) -> tuple[str, ...]:
    """Słowa, po których da się szukać zamiast zdania.

    Najpierw technologie ze słownika stojące w zdaniu, potem rdzenie słów
    treści z gwiazdką i ich odpowiedniki z `keyword_equivalents.json`
    („przetarg*”, „PZP”, „SIWZ”). Podpowiedź, nie decyzja — przy każdej
    przeglądarka pokazuje liczbę osób w bazie.
    """
    from app.services.keyword_suggest import equivalents_for, fold

    out: list[str] = []
    seen: set[str] = set()

    def add(word: str) -> None:
        key = fold(word)
        if key and key not in seen and len(out) < MAX_SUGGESTIONS:
            seen.add(key)
            out.append(word)

    for name in _dictionary_names_in(text):
        add(name)
    for raw in _WORD.findall(text):
        word = raw.strip(".,-/")
        lower = word.casefold()
        if (
            len(lower) < _MIN_STEM
            or lower in _HEAD_FILLER_WORDS
            or lower in _STOP_WORDS
            or lower.isdigit()
        ):
            continue
        stem = _stem(word)
        if stem:
            add(stem)
        for candidate in (word, stem):
            for other in equivalents_for(candidate) if candidate else ():
                add(other)
    return tuple(out)


def _short(text: str) -> bool:
    from app.services.champion_requirement_rows import _is_keyword

    return _is_keyword(text)


def _city(text: str) -> bool:
    from app.services import pl_places

    if len(text.split()) > 3:
        return False
    place = pl_places.resolve(text)
    return place is not None and place.population >= CITY_POPULATION


def read_phrase(text: str) -> PhraseReading:
    """Jak system czyta frazę — patrz docstring modułu."""
    # Słowo wiersza ma najwyżej 100 znaków; przycięcie chroni pamięć
    # podręczną bramki przed kluczami z megabajtowego ciała żądania.
    clean = _clean((text or "")[:PHRASE_MAX_CHARS])
    if not clean:
        return PhraseReading(text, "prose", None, None, None, None, (), True)
    requirement = gate_requirement(clean)
    if requirement is not None:
        if _city(clean) and not critical_eligible(clean):
            return PhraseReading(clean, "city", None, None, None, None, (), True)
        base, _version = strip_version(clean)
        keyword = " lub ".join(requirement.options)
        comment: Optional[str] = None
        paren = _PAREN_TAIL.match(base)
        if paren and len(requirement.options) == 1:
            comment = _clean(paren.group("body")) or None
        elif fold_key(base) != fold_key(keyword) and not paren:
            # Wstęp wokół nazwy („Bardzo dobra znajomość SQL”).
            comment = base
        talk_text: Optional[str] = None
        if comment and _LEVEL_WORDS.search(comment):
            talk_text = _cap(clean if not paren else f"{keyword} — {comment}")
        kind = "technology" if critical_eligible(clean) else "keyword"
        return PhraseReading(
            clean,
            kind,
            keyword,
            comment,
            "skills" if talk_text else None,
            talk_text,
            (),
            False,
        )
    reason = ignored_reason(clean) or "prose"
    if reason in ("category", "role") and not _short(clean):
        # Zdanie ze słowem kategorii („Knowledge of card lifecycle management”)
        # to nie słowo do szukania — ta sama granica co `rows_from_legacy`.
        reason = "prose"
    if reason == "language":
        return PhraseReading(clean, "language", None, None, "language", clean, (), True)
    if reason == "soft":
        return PhraseReading(clean, "soft", None, None, "skills", _cap(clean), (), True)
    if reason == "prose":
        return PhraseReading(
            clean,
            "prose",
            None,
            None,
            "skills",
            _cap(clean),
            suggestions_for(clean),
            True,
        )
    if reason == "domain":
        # „bankowość” jako słowo kluczowe jest w porządku (mile widziane);
        # „doświadczenie w bankowości” to już zdanie do rozmowy.
        long = len(clean.split()) > 2 or any(
            w.casefold() in _HEAD_FILLER_WORDS for w in clean.split()
        )
        return PhraseReading(
            clean,
            "domain",
            None if long else clean,
            None,
            "domains",
            _cap(clean),
            suggestions_for(clean),
            long,
        )
    # Kategoria i rola: słowo do szukania (np. „mikroserwisy”, „Scrum Master”);
    # czy coś znajduje, mówi liczba osób przy wierszu.
    return PhraseReading(clean, reason, clean, None, None, None, (), False)


def fold_key(text: str) -> str:
    return " ".join(must_gate_terms._words(text))


def read_row(words: list[str]) -> list[PhraseReading]:
    return [read_phrase(word) for word in words if isinstance(word, str)]
