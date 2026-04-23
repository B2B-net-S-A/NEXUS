"""
Traffit-style boolean advanced search for candidates.

Builds a SQLAlchemy WHERE clause from three buckets of free-text phrases:
- `q_all`  — every phrase must appear in at least one searchable field (AND).
- `q_any`  — at least one phrase must appear (OR).
- `q_none` — no phrase may appear (NOT).

Each phrase matches case-insensitively as an ILIKE substring (`%phrase%`).
The filter composes as: AND(all_clause, any_clause, NOT p1, NOT p2, ...).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String, and_, cast, func, not_, or_
from sqlalchemy.sql import ColumnElement

from app.models.candidate import Candidate

_MAX_PHRASES_PER_BUCKET = 20
_MIN_PHRASE_LEN = 2


def _safe(col: ColumnElement) -> ColumnElement:
    """Coalesce NULL to empty string so ILIKE never yields NULL.

    Critical for the NOT bucket: ``NOT(ilike(NULL, ...))`` evaluates to NULL,
    which ``WHERE`` treats as excluded. ``COALESCE(col, '')`` keeps the
    boolean three-valued logic sane.
    """
    return func.coalesce(col, "")


_SEARCHABLE_COLUMNS: list[ColumnElement] = [
    _safe(Candidate.name),
    _safe(Candidate.lastname),
    _safe(Candidate.email),
    _safe(Candidate.raw_cv_text),
    _safe(Candidate.ai_summary),
    _safe(Candidate.competence_category),
    _safe(cast(Candidate.experience, String)),
    _safe(cast(Candidate.skills, String)),
    _safe(cast(Candidate.tags, String)),
]


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is treated literally."""
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def _phrase_match(phrase: str) -> ColumnElement:
    """OR across all searchable columns for a single phrase."""
    pattern = f"%{_escape_like(phrase)}%"
    return or_(*(col.ilike(pattern, escape="\\") for col in _SEARCHABLE_COLUMNS))


def _clean(phrases: Optional[list[str]]) -> list[str]:
    """Strip, drop blanks / too-short / duplicates (case-insensitive), cap at limit."""
    if not phrases:
        return []
    seen: set[str] = set()
    cleaned: list[str] = []
    for raw in phrases:
        if raw is None:
            continue
        trimmed = raw.strip()
        key = trimmed.lower()
        if len(trimmed) >= _MIN_PHRASE_LEN and key not in seen:
            seen.add(key)
            cleaned.append(trimmed)
        if len(cleaned) >= _MAX_PHRASES_PER_BUCKET:
            break
    return cleaned


def build_advanced_filter(
    q_all: Optional[list[str]],
    q_any: Optional[list[str]],
    q_none: Optional[list[str]],
) -> Optional[ColumnElement]:
    """
    Combine the three buckets into a single SQLAlchemy expression.

    Returns `None` when all buckets are effectively empty — caller should
    skip the `.where(...)` call in that case.
    """
    all_phrases = _clean(q_all)
    any_phrases = _clean(q_any)
    none_phrases = _clean(q_none)

    clauses: list[ColumnElement] = []
    if all_phrases:
        clauses.append(and_(*(_phrase_match(p) for p in all_phrases)))
    if any_phrases:
        clauses.append(or_(*(_phrase_match(p) for p in any_phrases)))
    if none_phrases:
        clauses.extend(not_(_phrase_match(p)) for p in none_phrases)

    if not clauses:
        return None
    return and_(*clauses)
