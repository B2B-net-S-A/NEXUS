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

# All keys/values lowercase. Empty until hydrated so offline use degrades.
TECH_CANONICALS: set[str] = set()  # canonical names whose category ∈ TECH_CATEGORIES
ALIAS_TO_CANONICAL: dict[str, str] = {}  # alias -> canonical (ALL skills)
CANONICAL_TO_ALIASES: dict[str, list[str]] = {}  # tech canonical -> [alias, ...]


def set_tech_taxonomy(
    *,
    tech_canonicals,
    alias_to_canonical: dict[str, str],
    canonical_to_aliases: dict[str, list[str]] | None = None,
) -> None:
    """Replace the in-memory tech taxonomy atomically (called at startup)."""
    TECH_CANONICALS.clear()
    TECH_CANONICALS.update(c.strip().lower() for c in tech_canonicals if c)
    ALIAS_TO_CANONICAL.clear()
    ALIAS_TO_CANONICAL.update(
        {a.strip().lower(): c.strip().lower() for a, c in alias_to_canonical.items() if a and c}
    )
    CANONICAL_TO_ALIASES.clear()
    for canon, aliases in (canonical_to_aliases or {}).items():
        CANONICAL_TO_ALIASES[canon.strip().lower()] = [a.strip().lower() for a in aliases if a]


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
