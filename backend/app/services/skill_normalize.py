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


def set_tech_taxonomy(
    *,
    tech_canonicals,
    alias_to_canonical: dict[str, str],
    canonical_to_aliases: dict[str, list[str]] | None = None,
    categories: dict[str, str] | None = None,
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
    return base, match.group(0).strip().strip("()").strip()
