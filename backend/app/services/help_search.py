"""Ranking procedur Pomocy dla pytań zadanych zdaniem (Jarvis).

Wyszukiwarka ekranu Pomocy wymaga trafienia KAŻDEGO słowa (ILIKE, AND) —
dobre dla dwóch pamiętanych słów, złe dla pytania „jak dodać zamówienie
z pdf”, w którym „jak” i „dodać” zerują wynik. Tu liczymy punkty w Pythonie:
procedur jest kilkadziesiąt, a produkcja nie ma rozszerzenia ``unaccent``.

- polskie znaki i wielkość liter nie mają znaczenia (``fold``);
- słowa-wypełniacze odpadają;
- słowo pasuje po wspólnym początku (5 znaków) — „zamówienia” trafia
  „zamówienie”, bez pełnego stemmera;
- trafienie w tytule waży ×3, w nagłówku sekcji ×2, w treści ×1.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

_STOPWORDS = frozenset(
    {
        "jak",
        "gdzie",
        "czy",
        "co",
        "sie",
        "na",
        "do",
        "w",
        "z",
        "i",
        "o",
        "mam",
        "moge",
        "jest",
        "to",
        "ten",
        "ta",
        "te",
        "tu",
        "tym",
        "tego",
        "dla",
        "po",
        "od",
        "za",
        "przy",
        "nie",
        "mnie",
        "mi",
        "ja",
        "zrobic",
        "mozna",
        "trzeba",
        "ktory",
        "ktora",
        "ktore",
    }
)
_PREFIX = 5
_TOKEN = re.compile(r"[a-z0-9]+")
_HEADING = re.compile(r"^#{2,3}\s+(.+)$", re.MULTILINE)
MAX_RESULTS = 8
EXCERPT_CHARS = 200


def fold(text: str) -> str:
    """Małe litery bez znaków diakrytycznych (``ł`` ręcznie — NFKD go nie rozkłada)."""
    lowered = (text or "").lower().replace("ł", "l")
    decomposed = unicodedata.normalize("NFKD", lowered)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def query_terms(query: str) -> list[str]:
    terms: list[str] = []
    for token in _TOKEN.findall(fold(query)):
        if len(token) < 3 or token in _STOPWORDS:
            continue
        stem = token[:_PREFIX]
        if stem not in terms:
            terms.append(stem)
    return terms[:12]


def _hits(stems: list[str], text: str) -> int:
    tokens = _TOKEN.findall(fold(text))
    return sum(1 for stem in stems if any(t.startswith(stem) for t in tokens))


@dataclass(frozen=True)
class RankedDoc:
    key: object
    score: float
    excerpt: Optional[str]


def excerpt_for(stems: list[str], content: str) -> Optional[str]:
    """Fragment treści wokół pierwszego trafienia (bez nagłówków Markdown)."""
    if not content:
        return None
    folded = fold(content)
    first = None
    for stem in stems:
        match = re.search(rf"\b{re.escape(stem)}", folded)
        if match and (first is None or match.start() < first):
            first = match.start()
    if first is None:
        return None
    # fold nie zmienia długości poza znakami łączącymi, które usuwa — indeks
    # z wersji złożonej jest przybliżeniem; wystarcza do wycięcia okna.
    start = max(0, first - EXCERPT_CHARS // 3)
    window = content[start : start + EXCERPT_CHARS]
    window = re.sub(r"[#*_`>|]+", " ", window)
    window = " ".join(window.split())
    prefix = "…" if start > 0 else ""
    suffix = "…" if start + EXCERPT_CHARS < len(content) else ""
    return f"{prefix}{window}{suffix}" if window else None


def rank(query: str, docs: Iterable[tuple[object, str, str]]) -> list[RankedDoc]:
    """``docs`` = (klucz, tytuł, treść). Zwraca najwyżej ``MAX_RESULTS`` trafień."""
    stems = query_terms(query)
    if not stems:
        return []
    ranked: list[RankedDoc] = []
    for key, title, content in docs:
        headings = " ".join(_HEADING.findall(content or ""))
        score = (
            3 * _hits(stems, title or "")
            + 2 * _hits(stems, headings)
            + _hits(stems, content or "")
        )
        if score > 0:
            ranked.append(
                RankedDoc(
                    key=key,
                    score=float(score),
                    excerpt=excerpt_for(stems, content or ""),
                )
            )
    ranked.sort(key=lambda d: d.score, reverse=True)
    return ranked[:MAX_RESULTS]
