"""Dependency-free skill-name parsing + technology-taxonomy state.

Shared by the CV generator (``champion_builder`` extraction, ``docx_renderer``
bolding) so both interpret the same JSONB skill shapes and the same
``skills``/``skill_aliases`` taxonomy as the matching engine — but WITHOUT
importing ORM models or config. It depends only on ``re``/``json`` so the
renderer (which pulls no DB deps) and offline test harnesses can import it.

The tech-taxonomy maps are hydrated once at startup from the database by
``skill_taxonomy_loader.refresh_alias_map`` (via :func:`set_tech_taxonomy`) and
are EMPTY by default, so tests and offline tools work without a DB — callers
degrade to their own heuristics when the taxonomy is not loaded.

NOTE (parity): the JSONB-shape logic in :func:`iter_skill_names` intentionally
mirrors ``scoring_service._skill_names`` (which lowercases). It is duplicated
rather than shared to keep the critical matching engine untouched; keep the two
in sync if the accepted shapes change.
"""

from __future__ import annotations

import json
import re

# ── JSONB skill-name parsing (case-preserving) ──────────────────────────────

DICT_SKILL_LIST_KEYS = ("technologies", "skills", "stack", "tech")


def split_skill_tokens(text: str) -> list[str]:
    """Split a free-form skills string on comma/semicolon/newline (NOT ``/`` so
    ``CI/CD``/``TCP/IP`` survive). Case-preserving, stripped, empties dropped."""
    if not text:
        return []
    return [t.strip() for t in re.split(r"[,;\n]+", text) if t.strip()]


def iter_skill_names(raw) -> list[str]:
    """Extract skill NAME strings from any JSONB shape, preserving case.

    Accepted shapes (prod jobs mix them):
      - list[str]                              -> ["Java", "Go"]
      - list[dict]                             -> [{"name": "Java"}, ...]
      - dict with "name"                       -> {"name": "Java"}
      - dict with a list under DICT_SKILL_LIST_KEYS -> {"technologies": [...]}
      - str: JSON-encoded array/object ('["Java"]') OR comma list ("Java, Go")

    Anything else yields [] (silent, matching scoring_service). Unlike the
    scoring variant this does NOT lowercase — champion display/bolding needs the
    original case ("React", not "react").
    """
    out: list[str] = []
    if not raw:
        return out
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                name = item.get("name")
                if name:
                    out.append(str(name).strip())
            elif isinstance(item, str):
                out.append(item.strip())
    elif isinstance(raw, dict):
        name = raw.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
        for key in DICT_SKILL_LIST_KEYS:
            value = raw.get(key)
            if isinstance(value, list):
                out.extend(iter_skill_names(value))
    elif isinstance(raw, str):
        stripped = raw.strip()
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                parsed = json.loads(stripped)
            except (ValueError, TypeError):
                parsed = None
            if isinstance(parsed, (list, dict)):
                return iter_skill_names(parsed)
        out.extend(split_skill_tokens(stripped))
    return [s for s in out if s]


# ── Technology taxonomy (hydrated at startup from skills/skill_aliases) ──────
#
# Categories in the `skills` table that count as "a concrete technology" for CV
# bolding — languages, frameworks, tools, platforms. Deliberately EXCLUDES
# `methodology` (Agile/Scrum) and all `role_*` buckets (analyst/manager roles)
# so they never bold. Includes `api`/`framework`/`messaging` — present in the
# production taxonomy but absent from the local seed script.
TECH_CATEGORIES = frozenset(
    {
        "language",
        "frontend",
        "backend",
        "database",
        "devops",
        "cloud",
        "data",
        "qa",
        "mobile",
        "security",
        "api",
        "framework",
        "messaging",
    }
)

# Technologie w sensie bramki must i umiejętności krytycznych (30.09.2026):
# kategorie CV plus narzędzia (Pega, SAP, IBM MQ, Camunda, OpenShift), standardy
# (UML, BPMN, OpenAPI) i AI. Osobny zbiór, bo TECH_CATEGORIES steruje też
# pogrubianiem w CV — dopisanie tam narzędzi zmieniłoby wygląd każdego CV.
GATE_TECH_CATEGORIES = TECH_CATEGORIES | frozenset({"tools", "standards", "ai"})

# All keys/values lowercase. Empty until hydrated so offline use degrades.
TECH_CANONICALS: set[str] = set()  # canonical names whose category ∈ TECH_CATEGORIES
CANONICAL_CATEGORY: dict[str, str] = {}  # canonical -> category (ALL skills)
ALIAS_TO_CANONICAL: dict[str, str] = {}  # alias -> canonical (ALL skills)
CANONICAL_TO_ALIASES: dict[str, list[str]] = {}  # tech canonical -> [alias, ...]
# Etap 3a (0659): warianty, które liczą się w tekście CV (canonical -> [alias]),
# dla wszystkich kategorii poza rolami — QC i strażnik generatora.
TEXT_ALIASES: dict[str, list[str]] = {}


def set_tech_taxonomy(
    *,
    tech_canonicals,
    alias_to_canonical: dict[str, str],
    canonical_to_aliases: dict[str, list[str]] | None = None,
    categories: dict[str, str] | None = None,
    text_aliases: dict[str, list[str]] | None = None,
) -> None:
    """Replace the in-memory tech taxonomy atomically (called at startup)."""
    CANONICAL_CATEGORY.clear()
    CANONICAL_CATEGORY.update(
        {
            c.strip().lower(): (cat or "").strip().lower()
            for c, cat in (categories or {}).items()
            if c
        }
    )
    TECH_CANONICALS.clear()
    TECH_CANONICALS.update(c.strip().lower() for c in tech_canonicals if c)
    ALIAS_TO_CANONICAL.clear()
    ALIAS_TO_CANONICAL.update(
        {
            a.strip().lower(): c.strip().lower()
            for a, c in alias_to_canonical.items()
            if a and c
        }
    )
    CANONICAL_TO_ALIASES.clear()
    for canon, aliases in (canonical_to_aliases or {}).items():
        CANONICAL_TO_ALIASES[canon.strip().lower()] = [
            a.strip().lower() for a in aliases if a
        ]
    TEXT_ALIASES.clear()
    for canon, aliases in (text_aliases or {}).items():
        TEXT_ALIASES[canon.strip().lower()] = [a.strip().lower() for a in aliases if a]


def canonical_of(name: str) -> str:
    """Resolve an alias/canonical (any case) to its canonical (lower); pass
    through the lowered input when unknown or when the taxonomy is empty."""
    low = (name or "").strip().lower()
    return ALIAS_TO_CANONICAL.get(low, low)


def is_taxonomy_technology(name: str) -> bool:
    """True iff `name` canonicalizes to a taxonomy skill in a tech category.
    Always False when the taxonomy is not hydrated (offline/tests)."""
    if not TECH_CANONICALS:
        return False
    return canonical_of(name) in TECH_CANONICALS


def taxonomy_category(name: str) -> str | None:
    """Kategoria nazwy ze słownika (``role_dev``, ``tools``…) albo ``None``,
    gdy nazwy nie ma w słowniku albo słownik nie jest wczytany."""
    return CANONICAL_CATEGORY.get(canonical_of(name)) or None


def is_gate_technology(name: str) -> bool:
    """Czy nazwa jest technologią ze słownika w sensie bramki must
    (``GATE_TECH_CATEGORIES``). ``False`` bez wczytanego słownika."""
    return taxonomy_category(name) in GATE_TECH_CATEGORIES


def is_single_letter_skill(word: str) -> bool:
    """Jednoliterowa nazwa technologii ze słownika („C”, „R”) — nie szum.

    Wspólna reguła wierszy wymagań, odczytu maila i słów kluczowych (audyt
    06.10.2026, P4/K4): limit „co najmniej 2 znaki” wycinał je po cichu, więc
    rekrutacji na programistę C nie dało się opisać wierszem. Każda inna
    pojedyncza litera dalej jest szumem. ``False`` bez wczytanego słownika.
    """
    text = (word or "").strip()
    return len(text) == 1 and text.isalpha() and is_gate_technology(text)


def cut_at_word(text: str, limit: int) -> str:
    """Tekst przycięty do ``limit`` znaków na granicy słowa (bez urwanego wyrazu).

    Słowo dłuższe niż limit (bez spacji) jest przycinane twardo — nie ma tu
    granicy, na której można by się zatrzymać.
    """
    if len(text) <= limit:
        return text
    head = text[: limit + 1]
    cut = head.rfind(" ")
    return (head[:cut] if cut > 0 else text[:limit]).rstrip()


def is_non_technology_concept(name: str) -> bool:
    """Nazwa ze słownika, która jest rolą albo metodyką („QA”, „Software
    developer”, „Scrum”) — nie technologią, więc nie bramkuje."""
    category = taxonomy_category(name) or ""
    return category.startswith("role_") or category == "methodology"


def tech_alias_forms(name: str) -> list[str]:
    """All lowercase surface forms (canonical + its aliases + the input) for a
    taxonomy technology — used to build bold patterns so a chip written as
    ``ReactJS`` also bolds ``React`` in the CV (and vice-versa). Returns [] when
    `name` is not a taxonomy technology (or the taxonomy is not hydrated)."""
    if not TECH_CANONICALS:
        return []
    canon = canonical_of(name)
    if canon not in TECH_CANONICALS:
        return []
    forms = {canon, (name or "").strip().lower()}
    forms.update(CANONICAL_TO_ALIASES.get(canon, []))
    return sorted(f for f in forms if f)


def bold_alias_forms(name: str) -> list[str]:
    """Formy, którymi generator CV pogrubia wymaganie (G2, 07.11.2026).

    Technologia jak w :func:`tech_alias_forms`. Narzędzie, standard i AI
    (``GATE_TECH_CATEGORIES`` — te same, które bramkują krytyczne) dają hasło
    i warianty liczące się w tekście CV (``TEXT_ALIASES``, bez jednego słowa
    z wielowyrazowej nazwy), bo „SailPoint IIQ” z wymagań to „SailPoint
    IdentityIQ” w CV. Pomiar na 326 zatwierdzonych CV: rekruterzy dopisywali
    ręcznie pogrubienia narzędzi z must/nice (Pega, Bamboo, Appium, VMware),
    których generator nie uznawał za technologie. Metodyka, praktyka, dziedzina
    i rola zostają bez pogrubienia. Pusta lista spoza tych kategorii."""
    forms = tech_alias_forms(name)
    if forms:
        return forms
    canon = canonical_of(name)
    if CANONICAL_CATEGORY.get(canon) not in GATE_TECH_CATEGORIES:
        return []
    out = {canon, (name or "").strip().lower(), *TEXT_ALIASES.get(canon, [])}
    return sorted(f for f in out if f)


# Jedno słowo, które jest wariantem hasła, a w zdaniu zwykle znaczy coś innego:
# „Access Management” to nie MS Access, „Apache Iceberg” to nie serwer Apache
# (pomiar G2 na 326 CV: „access” pogrubiało się 42 razy bez sensu).
_AMBIGUOUS_MENTIONS = frozenset(
    {"access", "project", "word", "teams", "office", "apache", "outlook", "visio"}
)


def is_bold_technology_mention(text: str) -> bool:
    """Czy fraza ze zdania wymagania to nazwa, którą generator pogrubia: hasło
    albo wariant liczący się w tekście (``TEXT_ALIASES``) technologii,
    narzędzia, standardu lub AI. Sam alias nie wystarczy — „Project” to
    w słowniku „Microsoft Project”, ale w zdaniu znaczy „projekt”."""
    low = (text or "").strip().lower()
    if low in _AMBIGUOUS_MENTIONS:
        return False
    canon = canonical_of(low)
    if canon not in TECH_CANONICALS and CANONICAL_CATEGORY.get(canon) not in (
        GATE_TECH_CATEGORIES
    ):
        return False
    return low == canon or low in TEXT_ALIASES.get(canon, ())


_NAME_WORD = re.compile(r"[0-9a-ząćęłńóśźż+#.]+")


def alias_counts_in_text(
    alias: str, canonical: str, category: str | None, flag: bool | None
) -> bool:
    """Czy wariant liczy się, gdy QC i strażnik generatora szukają wymagania
    w tekście CV (etap 3a słownika, decyzja Artura 07.11.2026).

    ``flag`` to decyzja osoby prowadzącej słownik (``skill_aliases.in_text``)
    i wygrywa zawsze. Bez niej: wariant technologii liczy się jak dotąd,
    a przy narzędziach, metodykach, AI, standardach i dziedzinach nie liczy
    się jedno słowo, które jest częścią wielowyrazowej nazwy („project” przy
    „Microsoft Project”, „word”, „teams”) — samo uznałoby brak za trafienie.
    Role nie mają wariantów w tekście.
    """
    cat = (category or "").strip().lower()
    if cat.startswith("role_"):
        return False
    if flag is not None:
        return flag
    if cat in TECH_CATEGORIES:
        return True
    text = (alias or "").strip().lower()
    words = _NAME_WORD.findall((canonical or "").lower())
    return not (len(words) > 1 and " " not in text and text in words)


def text_alias_forms(name: str) -> list[str]:
    """Formy nazwy do szukania w tekście CV: nazwa, hasło słownika i warianty,
    które się w tekście liczą (``alias_counts_in_text``). Pusta lista dla
    roli, nazwy spoza słownika albo niewczytanego słownika — wtedy szukamy
    samej nazwy, jak dotąd."""
    canon = canonical_of(name)
    category = CANONICAL_CATEGORY.get(canon)
    if category is None or category.startswith("role_"):
        return []
    forms = {canon, (name or "").strip().lower()}
    forms.update(TEXT_ALIASES.get(canon, []))
    return sorted(f for f in forms if f)


# ── Technologie, które spełniają wymaganie ogólniejsze ─────────────────────

# „SQL” w wymaganiach spełnia każdy, kto pracuje z bazą SQL-ową — w CV pisze
# się wtedy nazwę bazy („PostgreSQL & MySQL”), nie samo „SQL”. Ukrywało to
# trafne osoby za bramką krytycznych (pomiar 07.10.2026: 10 z 271 ukryć).
# To IMPLIKACJA, nie alias: PostgreSQL spełnia SQL, ale SQL nie spełnia
# PostgreSQL — dlatego nie w `skill_aliases` (alias jest dwukierunkowy).
IMPLIED_BY: dict[str, tuple[str, ...]] = {
    "sql": (
        "postgresql",
        "postgres",
        "mysql",
        "microsoft sql server",
        "ms sql",
        "mssql",
        "sql server",
        "mariadb",
        "sqlite",
        "t-sql",
        "pl/sql",
    ),
    "uml": ("plantuml",),
}


# Mapa wiedzy IT (0660, decyzja Artura z 07.11.2026): zatwierdzone powiązania
# ze `skill_relations`, wczytywane razem ze słownikiem (`skill_taxonomy_loader`).
# Klucz i wartości to hasła słownika małymi literami.
RELATION_IMPLIED_BY: dict[str, set[str]] = {}  # „wynika z” i „część”: do -> {od}
RELATION_ALTERNATIVES: dict[str, set[str]] = {}  # zamienniki, w obie strony
RELATION_TYPICAL_BY: dict[str, set[str]] = {}  # „typowe”: do -> {od}


def set_relations(
    *,
    implied_by: dict[str, set[str]] | None = None,
    alternatives: dict[str, set[str]] | None = None,
    typical_by: dict[str, set[str]] | None = None,
) -> None:
    """Podmień powiązania w pamięci (start aplikacji i każda zmiana słownika)."""
    for target, source in (
        (RELATION_IMPLIED_BY, implied_by),
        (RELATION_ALTERNATIVES, alternatives),
        (RELATION_TYPICAL_BY, typical_by),
    ):
        target.clear()
        for key, values in (source or {}).items():
            target[key.strip().lower()] = {v.strip().lower() for v in values if v}


def _forms_of(canonicals: set[str]) -> list[str]:
    """Hasła razem z ich wariantami, bez duplikatów, w stałej kolejności."""
    forms: set[str] = set()
    for canon in canonicals:
        forms.add(canon)
        forms.update(CANONICAL_TO_ALIASES.get(canon, []))
    return sorted(f for f in forms if f)


def implied_forms(name: str, *, relations: bool = True) -> tuple[str, ...]:
    """Formy, które spełniają wymaganie `name` (puste, gdy nie ma implikacji):
    stała rodzina SQL/UML i zatwierdzone powiązania „wynika z” i „część”
    (Spring Boot ⇒ Java, GitHub ⇒ Git) razem z wariantami tych haseł.
    ``relations=False`` = sama stała rodzina (dowód dosłowny w punktacji)."""
    low = (name or "").strip().lower()
    canon = canonical_of(low)
    static = IMPLIED_BY.get(low) or IMPLIED_BY.get(canon) or ()
    related = RELATION_IMPLIED_BY.get(canon) if relations else None
    if not related:
        return static
    return tuple(dict.fromkeys([*static, *_forms_of(related)]))


def has_relation_implication(name: str) -> bool:
    """Czy wymaganie ma zatwierdzone powiązanie „wynika z” albo „część”."""
    return bool(RELATION_IMPLIED_BY.get(canonical_of(name)))


def alternative_forms(name: str) -> tuple[str, ...]:
    """Zamienniki wymagania (Flask przy FastAPI) z wariantami. Nie spełniają
    wymagania — zamieniają „brak” w pytanie do rozmowy."""
    related = RELATION_ALTERNATIVES.get(canonical_of(name))
    return tuple(_forms_of(related)) if related else ()


def typical_sources(name: str) -> tuple[str, ...]:
    """Hasła, przy których wymaganie jest typowe (Java przy Maven), z wariantami.
    Nie spełniają wymagania — dają pytanie do rozmowy."""
    related = RELATION_TYPICAL_BY.get(canonical_of(name))
    return tuple(_forms_of(related)) if related else ()


# ── Wersja przy nazwie technologii (bramka must, formularz rekrutacji) ──────

# „Java 8+”, „Python 3.x”, „Angular 15”, „.NET 6”, „Java 7/8”,
# „React.js (v18 or higher)”, „Java 11 or higher”. Formy sklejone z nazwą
# („ES6”, „S3”, „OAuth2”, „Log4j”) zostają — tam cyfra jest częścią nazwy.
# Wersja bywa też słowna: „Java (minimalna 11)”, „Oracle (min. 19c)”, „Java
# od 11” — bez tych słów cała pozycja wypadała z bramki i z wyboru krytycznych
# (produkcja 30.09.2026).
_VERSION_WORD = (
    r"(?:v\.?|ver\.?|version|wersja|wersji|min\.?|minimum|minimaln\w*|od|from|"
    r"at\s+least|co\s+najmniej|>=|≥)"
)
_VERSION_TAIL = re.compile(
    rf"(?:\s*\((?:{_VERSION_WORD}\s?)?\d[^()]*\)"
    rf"|\s+(?:{_VERSION_WORD}\s?)?\d+(?:[.,/]\d+)*(?:\.x|[a-z])?\s*\+?"
    r"(?:\s*(?:or|lub|and)\s*(?:higher|newer|above|wyżej|wyzej|nowsz\w*|nowsza|później|pozniej))?)\s*$",
    re.IGNORECASE,
)


def strip_version(name: str) -> tuple[str, str | None]:
    """Nazwa bez wersji i odcięta wersja: „Java 8+” → („Java”, „8+”).

    Bez wersji zwraca (nazwa, None). Nazwa złożona z samej wersji nie jest
    ucinana do pustego napisu.
    """
    text = (name or "").strip()
    match = _VERSION_TAIL.search(text)
    if not match or match.start() == 0:
        return text, None
    base = text[: match.start()].strip()
    if not base:
        return text, None
    # „OWASP Top 10”, „CWE Top 25” — liczba jest częścią nazwy (13.10.2026).
    if re.search(r"\btop$", base, re.IGNORECASE):
        return text, None
    return base, match.group(0).strip().strip("()").strip()
