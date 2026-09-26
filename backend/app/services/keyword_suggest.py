"""Podpowiedzi do pól słów kluczowych wyszukiwania ręcznego.

Źródła: słownik umiejętności (``skills`` + ``skill_aliases``, w pamięci
procesu — przebudowuje go ``skill_taxonomy_loader.refresh_alias_map``) oraz
stanowiska z doświadczenia kandydatów (to samo zapytanie co
``/api/candidates/titles/suggest``).

Wybór podpowiedzi wstawia do pola NAZWĘ KANONICZNĄ. Słowa kluczowe nie
rozwijają aliasów (dopasowanie dosłowne, ``keyword_terms``), więc alias jest
tylko wyjaśnieniem, dlaczego pozycja się pojawiła — nie obietnicą trafień po
nim. Liczba osób to przybliżenie z indeksu pełnotekstowego ``keyword_fts``
(bez gałęzi regex i notatek), dlatego front pisze ją z tyldą; brak odpowiedzi
w limicie czasu albo trwające wypełnianie korpusu = ``None``, nigdy błąd.
"""

from __future__ import annotations

import logging
import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.polish_ilike import contains_pattern
from app.services import keyword_corpus
from app.services.keyword_terms import (
    MIN_WILDCARD_CORE,
    parse_keyword,
    pg_regex,
    tsquery_path_variants,
    tsquery_text,
)

logger = logging.getLogger(__name__)

_WORD_SPLIT = re.compile(r"[\s./#+\-()_,]+")
COUNT_TTL_SECONDS = 3600
COUNT_TIMEOUT_MS = 500
# Stanowiska to pełny przegląd `experience` (~220 ms na produkcji, 25.09.2026).
TITLES_TIMEOUT_MS = 1000
_COUNT_CACHE_MAX = 5000


def fold(value: str) -> str:
    """Małe litery, bez polskich znaków, pojedyncze spacje."""
    lowered = (value or "").lower().replace("ł", "l")
    stripped = "".join(
        ch
        for ch in unicodedata.normalize("NFKD", lowered)
        if not unicodedata.combining(ch)
    )
    return " ".join(stripped.split())


@dataclass(frozen=True)
class SkillEntry:
    label: str
    category: str
    aliases: tuple[str, ...]
    key: str
    word_keys: tuple[str, ...]
    alias_keys: tuple[str, ...]


_catalog: tuple[SkillEntry, ...] = ()


def load_catalog(
    skills: Iterable[tuple[int, str, Optional[str]]],
    alias_rows: Iterable[tuple[int, str]],
) -> int:
    """Buduje słownik podpowiedzi z wierszy ``skills`` i ``skill_aliases``."""
    aliases: dict[int, list[str]] = {}
    for skill_id, alias in alias_rows:
        if alias:
            aliases.setdefault(skill_id, []).append(alias)
    entries: list[SkillEntry] = []
    for skill_id, name, category in skills:
        if not name or not name.strip():
            continue
        label = name.strip()
        key = fold(label)
        own = [a for a in aliases.get(skill_id, []) if fold(a) != key]
        entries.append(
            SkillEntry(
                label=label,
                category=category or "",
                aliases=tuple(own),
                key=key,
                word_keys=tuple(w for w in _WORD_SPLIT.split(key) if w),
                alias_keys=tuple(fold(a) for a in own),
            )
        )
    global _catalog
    _catalog = tuple(entries)
    return len(entries)


def catalog() -> tuple[SkillEntry, ...]:
    return _catalog


@dataclass(frozen=True)
class SkillMatch:
    entry: SkillEntry
    alias: Optional[str]
    starts: bool


_MAX_PHRASE_WORDS = 4
_CLASSIFY_SPLIT = re.compile(r"[\s,;]+")


@dataclass(frozen=True)
class Classification:
    skills: tuple[str, ...]
    all_skills: bool


def classify_skills(query: str) -> Classification:
    """Czy tekst to same nazwy technologii (górne pole listy, 25.09.2026).

    Dopasowanie DOKŁADNE nazwy albo aliasu ze słownika (bez wielkości liter
    i polskich znaków), najdłuższe frazy najpierw („spring boot” jako jedna
    umiejętność). ``all_skills`` tylko, gdy każde słowo należy do jakiejś
    nazwy — zdanie opisowe („senior java z bankowością”) zostaje tekstem.
    Nazwiska i miejscowości sprawdza wołający (baza, spis miejscowości).
    """
    words = [w for w in _CLASSIFY_SPLIT.split(fold(query)) if w]
    if not words or not _catalog:
        return Classification(skills=(), all_skills=False)
    index: dict[str, str] = {}
    for entry in _catalog:
        index.setdefault(entry.key, entry.label)
        for alias_key in entry.alias_keys:
            index.setdefault(alias_key, entry.label)
    found: list[str] = []
    i = 0
    while i < len(words):
        for j in range(min(len(words), i + _MAX_PHRASE_WORDS), i, -1):
            label = index.get(" ".join(words[i:j]))
            if label is not None:
                found.append(label)
                i = j
                break
        else:
            return Classification(skills=tuple(dict.fromkeys(found)), all_skills=False)
    return Classification(skills=tuple(dict.fromkeys(found)), all_skills=True)


def match_skills(query: str, limit: int) -> list[SkillMatch]:
    """Umiejętności pasujące początkiem nazwy, słowa nazwy albo aliasu.

    Kolejność: początek całej nazwy, potem dokładny alias, potem reszta;
    w obrębie grupy krótsza nazwa pierwsza (``Java`` przed ``Java EE``).
    """
    q = fold(query)
    if not q:
        return []
    found: list[tuple[int, int, str, SkillMatch]] = []
    for entry in _catalog:
        starts = entry.key.startswith(q)
        alias_hit: Optional[str] = None
        if not starts:
            for alias, alias_key in zip(entry.aliases, entry.alias_keys):
                if alias_key.startswith(q):
                    alias_hit = alias
                    break
        word_hit = not starts and any(w.startswith(q) for w in entry.word_keys)
        if not (starts or alias_hit or word_hit):
            continue
        if starts:
            rank = 0
        elif alias_hit is not None and fold(alias_hit) == q:
            rank = 1
        else:
            rank = 2
        found.append(
            (rank, len(entry.label), entry.key, SkillMatch(entry, alias_hit, starts))
        )
    found.sort(key=lambda row: (row[0], row[1], row[2]))
    return [row[3] for row in found[:limit]]


async def suggest_titles(
    db: AsyncSession, q: str, limit: int, *, word_start: bool = False
) -> list[tuple[str, int]]:
    """Stanowiska z ``experience[].role`` (małe litery) z liczbą osób.

    ``word_start`` (podpowiedzi słów kluczowych): stanowisko musi mieć słowo
    zaczynające się od wpisanego tekstu — ta sama reguła co słowo kluczowe
    ``tekst*``. Bez niej „git” podpowiadał „digital project manager”, a „ora”
    — „doradca klienta” (produkcja, 25.09.2026). Filtr „Stanowisko”
    (``/titles/suggest``) zostaje przy podciągu.
    """
    pat = contains_pattern(q.strip().lower()) if q.strip() else ""
    term = parse_keyword(q.strip() + "*") if word_start and q.strip() else None
    word_re = pg_regex(term) if term is not None else ""
    sql = text(
        "SELECT lower(elem->>'role') AS role, COUNT(DISTINCT c.id) AS n "
        "FROM candidates c, "
        "jsonb_array_elements("
        "CASE WHEN jsonb_typeof(c.experience) = 'array' "
        "THEN c.experience ELSE '[]'::jsonb END"
        ") AS elem "
        "WHERE elem ? 'role' "
        "AND elem->>'role' IS NOT NULL "
        "AND elem->>'role' <> '' "
        "AND (:pat = '' OR lower(elem->>'role') LIKE :pat) "
        "AND (:word_re = '' OR lower(elem->>'role') ~* :word_re) "
        "GROUP BY lower(elem->>'role') "
        "ORDER BY n DESC, role ASC "
        "LIMIT :lim"
    )
    result = await db.execute(sql, {"pat": pat, "word_re": word_re, "lim": limit})
    return [(row[0], int(row[1])) for row in result]


TITLES_TTL_SECONDS = 600
_titles_cache: dict[tuple[str, int], tuple[float, list[tuple[str, int]]]] = {}


async def _titles_within_timeout(
    db: AsyncSession, q: str, limit: int
) -> list[tuple[str, int]]:
    key = (fold(q), limit)
    now = time.monotonic()
    hit = _titles_cache.get(key)
    if hit is not None and now - hit[0] < TITLES_TTL_SECONDS:
        return hit[1]
    rows = await _titles_query_within_timeout(db, q, limit)
    if rows is None:
        # Limit czasu nie trafia do pamięci — następny znak spróbuje znowu.
        return []
    if len(_titles_cache) > _COUNT_CACHE_MAX:
        _titles_cache.clear()
    _titles_cache[key] = (now, rows)
    return rows


async def _titles_query_within_timeout(
    db: AsyncSession, q: str, limit: int
) -> Optional[list[tuple[str, int]]]:
    """Stanowiska z limitem czasu w savepoincie — pełny przegląd
    ``experience`` przy każdym znaku nie może trzymać połączenia; po
    przekroczeniu lista zostaje bez stanowisk."""
    try:
        async with db.begin_nested():
            previous = (
                await db.execute(text("SELECT current_setting('statement_timeout')"))
            ).scalar_one()
            await db.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": f"{TITLES_TIMEOUT_MS}ms"},
            )
            rows = await suggest_titles(db, q, limit, word_start=True)
            await db.execute(
                text("SELECT set_config('statement_timeout', :prev, true)"),
                {"prev": previous},
            )
            return rows
    except Exception as exc:  # noqa: BLE001 — podpowiedź to dodatek
        logger.warning("keyword suggest titles skipped (%s)", type(exc).__name__)
        return None


_count_cache: dict[str, tuple[float, int]] = {}


def _tsquery_sql(value: str) -> Optional[str]:
    """Wyrażenie tsquery dla słowa kluczowego albo ``None`` (bez indeksu)."""
    term = parse_keyword(value)
    if term is None:
        return None
    tsq = tsquery_text(term)
    if tsq is None:
        return None
    return tsq


def _count_key(value: str) -> str:
    """Klucz liczby dla korpusu BEZ składania znaków (``keyword_fts``).

    Pisownia z polskimi znakami zostaje: „bankowość” i „bankowosc” to w tym
    indeksie różne słowa i różne liczby. Wielkość liter i spacje się nie
    liczą (``to_tsquery('simple', …)`` i tak zmniejsza litery).
    """
    return "raw:" + " ".join((value or "").split()).casefold()


def _cached(key: str, now: float) -> Optional[int]:
    hit = _count_cache.get(key)
    if hit is None or now - hit[0] > COUNT_TTL_SECONDS:
        return None
    return hit[1]


def clear_count_cache() -> None:
    _count_cache.clear()
    _titles_cache.clear()


async def count_candidates(
    db: AsyncSession, values: Sequence[str]
) -> dict[str, Optional[int]]:
    """Przybliżona liczba osób ze słowem w korpusie.

    Liczy wyłącznie po ``keyword_fts`` (indeks GIN); limit czasu zapytania
    obowiązuje w savepoincie, więc przekroczenie nie psuje transakcji żądania.
    """
    result: dict[str, Optional[int]] = {v: None for v in values}
    if not values:
        return result
    if keyword_corpus.folded_search_enabled():
        return await _count_folded(db, values, result)
    if not keyword_corpus.ready():
        return result
    now = time.monotonic()
    missing: list[tuple[str, str, Optional[str]]] = []
    for value in values:
        cached = _cached(_count_key(value), now)
        if cached is not None:
            result[value] = cached
            continue
        term = parse_keyword(value)
        # Fraza (`java <-> developer`) wymaga sprawdzenia pozycji w każdym
        # wierszu: 1,8–3,6 s na produkcji (25.09.2026). Liczymy tylko
        # pojedyncze słowa i początek słowa (`jav:*`) — 15–120 ms z indeksu.
        if term is None or not term.is_plain_word:
            continue
        tsq = _tsquery_sql(value)
        if tsq is None:
            continue
        variants = tsquery_path_variants(term) if term is not None else None
        missing.append((value, tsq, variants))
    if not missing:
        return result

    # Osobne zapytanie na słowo: sam indeks GIN liczy je w 10–25 ms.
    # Jedno zbiorcze z `count(*) FILTER (WHERE keyword_fts @@ …)` sprawdzało
    # tsvector każdego pasującego wiersza i trwało na produkcji 3 s
    # (25.09.2026) — limit czasu zerował wtedy każdą liczbę.
    if len(_count_cache) > _COUNT_CACHE_MAX:
        _count_cache.clear()
    for value, tsq, variants in missing:
        params: dict[str, object] = {"q": tsq}
        expr = "to_tsquery('simple', :q)"
        if variants is not None:
            params["v"] = variants
            expr = f"({expr} || CAST(:v AS tsquery))"
        sql = text(f"SELECT count(*) FROM candidates WHERE keyword_fts @@ {expr}")
        try:
            async with db.begin_nested():
                previous = (
                    await db.execute(
                        text("SELECT current_setting('statement_timeout')")
                    )
                ).scalar_one()
                await db.execute(
                    text("SELECT set_config('statement_timeout', :ms, true)"),
                    {"ms": f"{COUNT_TIMEOUT_MS}ms"},
                )
                n = int((await db.execute(sql, params)).scalar_one() or 0)
                await db.execute(
                    text("SELECT set_config('statement_timeout', :prev, true)"),
                    {"prev": previous},
                )
        except Exception as exc:  # noqa: BLE001 — liczba to dodatek, nie bramka
            logger.warning("keyword suggest count skipped (%s)", type(exc).__name__)
            continue
        result[value] = n
        _count_cache[_count_key(value)] = (now, n)
    return result


async def _count_one_within_timeout(db: AsyncSession, stmt) -> Optional[int]:
    try:
        async with db.begin_nested():
            previous = (
                await db.execute(text("SELECT current_setting('statement_timeout')"))
            ).scalar_one()
            await db.execute(
                text("SELECT set_config('statement_timeout', :ms, true)"),
                {"ms": f"{COUNT_TIMEOUT_MS}ms"},
            )
            n = int((await db.execute(stmt)).scalar_one() or 0)
            await db.execute(
                text("SELECT set_config('statement_timeout', :prev, true)"),
                {"prev": previous},
            )
            return n
    except Exception as exc:  # noqa: BLE001 — liczba to dodatek, nie bramka
        logger.warning("keyword suggest count skipped (%s)", type(exc).__name__)
        return None


async def _count_folded(
    db: AsyncSession, values: Sequence[str], result: dict[str, Optional[int]]
) -> dict[str, Optional[int]]:
    """Liczby z korpusu złożonego — to samo zapytanie co lista, więc liczba przy
    podpowiedzi zgadza się z wynikiem. Liczy też „c#”, „c++”, „.net”, „node.js”
    (pojedynczy token w indeksie). Frazy i słowa z ukośnikiem/myślnikiem
    pomijamy: sprawdzanie pozycji w każdym wierszu to sekundy."""
    from sqlalchemy import func, select  # noqa: PLC0415

    from app.models.candidate import Candidate  # noqa: PLC0415
    from app.services.advanced_candidate_search import (  # noqa: PLC0415
        folded_tsquery,
        keyword_fold_fts_column,
    )

    now = time.monotonic()
    if len(_count_cache) > _COUNT_CACHE_MAX:
        _count_cache.clear()
    for value in values:
        key = "fold:" + fold(value)
        cached = _cached(key, now)
        if cached is not None:
            result[value] = cached
            continue
        term = parse_keyword(value)
        if term is None or term.open_start or len(term.words) != 1:
            continue
        if any(ch in term.text for ch in "/\\-"):
            continue
        query = folded_tsquery(term)
        if query is None:
            continue
        stmt = (
            select(func.count())
            .select_from(Candidate)
            .where(keyword_fold_fts_column().op("@@")(query))
        )
        n = await _count_one_within_timeout(db, stmt)
        if n is None:
            continue
        result[value] = n
        _count_cache[key] = (now, n)
    return result


@dataclass(frozen=True)
class Suggestion:
    label: str
    kind: str
    insert: str
    alias: Optional[str]
    category: Optional[str]
    count: Optional[int]
    # Inne zapisy tej umiejętności do przycisku „+ z wariantami” (tylko skill).
    variants: tuple[str, ...] = ()


MAX_VARIANTS = 5


def skill_variants(entry: SkillEntry) -> tuple[str, ...]:
    """Aliasy umiejętności, które warto dopisać do wiersza wymagań.

    Słowa kluczowe dopasowują całe słowa i NIE rozwijają aliasów, więc
    „Springboot” nie znajdzie „Spring Boot” — stąd przycisk „+ z wariantami”
    (decyzja 25.09.2026: dodaje człowiek, nigdy automat). Odpadają: aliasy
    1–2-znakowe i polskie słowa-aliasy (ta sama lista co w scoringu, #1832:
    „go”, „jest”), aliasy zawierające pełną nazwę jako osobne słowo
    („java 11”, „core java” — znajdzie je już samo „java”) i takie, których
    nie da się szukać jako słowa.
    """
    from app.services.scoring_service import POLISH_WORD_ALIASES

    name_tokens = entry.key.split()
    out: list[str] = []
    seen = {entry.key}
    for alias in entry.aliases:
        key = fold(alias)
        if len(key) <= 2 or key in POLISH_WORD_ALIASES or key in seen:
            continue
        tokens = key.split()
        n = len(name_tokens)
        if any(tokens[i : i + n] == name_tokens for i in range(len(tokens) - n + 1)):
            continue
        if parse_keyword(alias) is None:
            continue
        seen.add(key)
        out.append(alias)
        if len(out) >= MAX_VARIANTS:
            break
    return tuple(out)


@dataclass(frozen=True)
class SuggestResult:
    items: list[Suggestion]
    wildcard: Optional[Suggestion]


def _label_word(entry: SkillEntry, alias: Optional[str]) -> Optional[str]:
    """Słowo nazwy równe aliasowi („Kafka” w „Apache Kafka” dla „kafka”).

    Słowa kluczowe dopasowują całe słowa, więc samo słowo znajduje każdego,
    kogo znajdzie fraza, i tych, którzy nie piszą całej nazwy: na produkcji
    „kafka” 4569 osób, „Apache Kafka” 1704 (decyzja Artura 25.09.2026).
    """
    if not alias:
        return None
    key = fold(alias)
    return next((w for w in entry.label.split() if fold(w) == key), None)


def skill_suggestions(query: str, limit: int) -> list[Suggestion]:
    """Podpowiedzi ze słownika, bez liczby osób (tę dolicza ``suggest``).

    Wstawiana jest nazwa kanoniczna („Springboot” → „Spring Boot”), chyba że
    podpowiedź trafiła przez alias będący osobnym słowem nazwy — wtedy to
    słowo, bo fraza zawęża wynik (``_label_word``).
    """
    out: list[Suggestion] = []
    for m in match_skills(query, limit):
        word = _label_word(m.entry, m.alias)
        out.append(
            Suggestion(
                label=word or m.entry.label,
                kind="skill",
                insert=word or m.entry.label,
                alias=m.entry.label if word else m.alias,
                category=m.entry.category or None,
                count=None,
                variants=skill_variants(m.entry),
            )
        )
    return out


def wildcard_for(query: str) -> Optional[str]:
    """``jav`` → ``jav*`` (rdzeń co najmniej ``MIN_WILDCARD_CORE`` znaków)."""
    core = " ".join((query or "").split()).strip("*").strip()
    if len(core) < MIN_WILDCARD_CORE or " " in core:
        return None
    return core + "*"


async def suggest(db: AsyncSession, query: str, limit: int) -> SuggestResult:
    q = " ".join((query or "").split())
    if not fold(q):
        return SuggestResult(items=[], wildcard=None)
    items: list[Suggestion] = skill_suggestions(q, limit)
    if len(fold(q)) >= 3 and len(items) < limit:
        seen = {fold(s.label) for s in items}
        for role, _n in await _titles_within_timeout(db, q, 3):
            if fold(role) in seen:
                continue
            items.append(
                Suggestion(
                    label=role,
                    kind="title",
                    insert=role,
                    alias=None,
                    category=None,
                    count=None,
                )
            )
            if len(items) >= limit:
                break
    wildcard_value = wildcard_for(q)
    counts = await count_candidates(
        db,
        [s.insert for s in items] + ([wildcard_value] if wildcard_value else []),
    )
    items = [Suggestion(**{**s.__dict__, "count": counts.get(s.insert)}) for s in items]
    wildcard = (
        Suggestion(
            label=wildcard_value,
            kind="prefix",
            insert=wildcard_value,
            alias=None,
            category=None,
            count=counts.get(wildcard_value),
        )
        if wildcard_value
        else None
    )
    return SuggestResult(items=items, wildcard=wildcard)
