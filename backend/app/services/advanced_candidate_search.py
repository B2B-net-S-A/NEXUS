"""
Traffit-style boolean advanced search for candidates.

Builds a SQLAlchemy WHERE clause from three buckets of free-text phrases:
- `q_all`  — every phrase must appear in at least one searchable field (AND).
- `q_any`  — at least one phrase must appear (OR). Supports MULTIPLE OR-groups
  that AND together (e.g. ``(react OR vue) AND (java OR kotlin)``) — the legacy
  flat ``q_any`` is group 0, extra groups arrive via ``q_any_groups``.
- `q_none` — no phrase may appear (NOT).

Each phrase matches case-insensitively as an ILIKE substring (`%phrase%`).
The filter composes as:
``AND(all_clause, OR(group_0), OR(group_1), ..., NOT p1, NOT p2, ...)``.

Search scope (Traffit parity, follow-up 2026-05-19):
- All scalar identity fields: name, lastname, email, phone, location, city,
  linkedin_current_title, linkedin_current_company.
- Free-text fields: raw_cv_text, ai_summary, competence_category, engagement_notes.
- JSONB blobs (cast to text): experience, skills, tags, education, languages.
- Notes content via EXISTS subquery to the `notes` table (notes are per-candidate
  rows, not columns, so they need a separate predicate that the bucket-match
  helper OR's with the column predicates).

This brings simple `?q=Python` and advanced `?q_all=Python` to the SAME scope
— the simple search delegates to `single_phrase_filter` so users see consistent
result counts whether or not they open the Boolean panel.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import String, and_, cast, exists, func, not_, or_
from sqlalchemy.sql import ColumnElement

from app.models.candidate import Candidate
from app.models.note import Note

_MAX_PHRASES_PER_BUCKET = 20
_MIN_PHRASE_LEN = 2
# Cap on the number of OR-groups in the ANY bucket. A defensive bound so a
# crafted URL can't fan out into an unbounded AND-of-ORs query plan.
_MAX_ANY_GROUPS = 10


def _safe(col: ColumnElement) -> ColumnElement:
    """Coalesce NULL to empty string so ILIKE never yields NULL.

    Critical for the NOT bucket: ``NOT(ilike(NULL, ...))`` evaluates to NULL,
    which ``WHERE`` treats as excluded. ``COALESCE(col, '')`` keeps the
    boolean three-valued logic sane.
    """
    return func.coalesce(col, "")


# Columns that participate in every phrase match. Order matters only for
# debugging — the OR is commutative. JSONB fields are cast to text so the
# whole JSON payload becomes a haystack — good enough for "find candidates
# whose CV mentions Python anywhere".
_SEARCHABLE_COLUMNS: list[ColumnElement] = [
    _safe(Candidate.name),
    _safe(Candidate.lastname),
    # Concatenated "name lastname" so a multi-word query like "Piotr Banulski"
    # matches via ILIKE — searching each column independently misses the
    # (name="Piotr", lastname="Banulski") case.
    func.concat_ws(" ", Candidate.name, Candidate.lastname),
    _safe(Candidate.email),
    _safe(Candidate.phone),
    _safe(Candidate.location),
    _safe(Candidate.city),
    _safe(Candidate.linkedin_current_title),
    _safe(Candidate.linkedin_current_company),
    _safe(Candidate.raw_cv_text),
    _safe(Candidate.ai_summary),
    _safe(Candidate.competence_category),
    _safe(Candidate.engagement_notes),
    _safe(cast(Candidate.experience, String)),
    _safe(cast(Candidate.skills, String)),
    _safe(cast(Candidate.tags, String)),
    _safe(cast(Candidate.education, String)),
    _safe(cast(Candidate.languages, String)),
]


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is treated literally."""
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def _note_match(phrase: str) -> ColumnElement:
    """EXISTS clause that fires when ANY note attached to the candidate
    contains the phrase (case-insensitive ILIKE).

    Notes live in their own table — joining for every search row would
    explode the result set with duplicates. EXISTS is an anti-join: it
    short-circuits on the first matching note per candidate, which is
    exactly what we want for "does the candidate have a note mentioning
    Python somewhere?". The Note model uses `candidate_id` as the FK.
    """
    pattern = f"%{_escape_like(phrase)}%"
    return exists().where(
        and_(
            Note.candidate_id == Candidate.id,
            Note.content.ilike(pattern, escape="\\"),
        )
    )


def _phrase_match(phrase: str) -> ColumnElement:
    """OR across all searchable columns + notes EXISTS for a single phrase."""
    pattern = f"%{_escape_like(phrase)}%"
    return or_(
        *(col.ilike(pattern, escape="\\") for col in _SEARCHABLE_COLUMNS),
        _note_match(phrase),
    )


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


def single_phrase_filter(phrase: str) -> Optional[ColumnElement]:
    """Build a WHERE clause for a single simple-search phrase.

    Used by the legacy `?q=...` parameter on GET /api/candidates to share
    the exact same field scope as the boolean `?q_all=...` path. Returns
    None when the phrase is too short to be useful — caller should skip
    the .where() in that case.
    """
    cleaned = _clean([phrase])
    if not cleaned:
        return None
    return _phrase_match(cleaned[0])


def build_advanced_filter(
    q_all: Optional[list[str]],
    q_any: Optional[list[str]],
    q_none: Optional[list[str]],
    q_any_groups: Optional[list[list[str]]] = None,
) -> Optional[ColumnElement]:
    """
    Combine the buckets into a single SQLAlchemy expression.

    The ANY bucket supports MULTIPLE OR-groups that AND together::

        (a OR b) AND (c OR d)

    ``q_any`` is the legacy single group; ``q_any_groups`` carries additional
    groups. Each group is cleaned/capped independently, contributes one
    ``OR(...)`` clause, and empty groups are dropped. This makes the ANY bucket
    a Traffit-style "any of these AND any of those" matcher rather than a single
    flat OR.

    Returns `None` when all buckets are effectively empty — caller should
    skip the `.where(...)` call in that case.
    """
    all_phrases = _clean(q_all)
    none_phrases = _clean(q_none)

    # Assemble every OR-group: the legacy flat ``q_any`` is group 0, followed
    # by any explicit extra groups. Clean each group independently and drop the
    # ones that come out empty so a stray blank group can't void the whole row.
    raw_groups: list[list[str]] = []
    if q_any:
        raw_groups.append(q_any)
    if q_any_groups:
        raw_groups.extend(q_any_groups)
    any_groups = [cleaned for group in raw_groups if (cleaned := _clean(group))]
    any_groups = any_groups[:_MAX_ANY_GROUPS]

    clauses: list[ColumnElement] = []
    if all_phrases:
        clauses.append(and_(*(_phrase_match(p) for p in all_phrases)))
    for group in any_groups:
        clauses.append(or_(*(_phrase_match(p) for p in group)))
    if none_phrases:
        clauses.extend(not_(_phrase_match(p)) for p in none_phrases)

    if not clauses:
        return None
    return and_(*clauses)
