"""Traffit-style boolean advanced search for candidates.

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
- Notes content (notes are per-candidate rows, not columns, so they need a
  separate predicate).

This brings simple `?q=Python` and advanced `?q_all=Python` to the SAME scope
— the simple search delegates to `single_phrase_filter` so users see consistent
result counts whether or not they open the Boolean panel.

Performance (2026-06-05): each phrase is matched as
``candidates.id IN (UNION of id-subqueries)`` rather than a single
OR-of-``COALESCE(col) ILIKE`` across 18 columns. The old shape forced a full
seq scan over 47.6K rows (~12s) because the ``COALESCE`` wrappers defeated index
matching and the OR mixed in a non-indexable ``similarity()`` filter and a
cross-table notes EXISTS — so the planner could use none of the trigram indexes.
The UNION lets every branch drive its own GIN ``pg_trgm`` index (an Append of
bitmap index scans, ~100-200ms):
  • ``search_doc``    → ``ix_candidates_search_doc_trgm`` (all non-CV columns;
    STORED generated column, migration 0126),
  • ``raw_cv_text``   → ``ix_candidates_cv_trgm`` (migration 0013),
  • ``notes.content`` → ``ix_notes_content_trgm`` (migration 0126).
Substring scope/semantics are unchanged (a candidate matches iff the phrase is a
substring of any searchable field or a note).
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Text, and_, column, func, not_, or_, select, union
from sqlalchemy.sql import ColumnElement

from app.models.candidate import Candidate
from app.models.note import Note

_MAX_PHRASES_PER_BUCKET = 20
_MIN_PHRASE_LEN = 2
# Cap on the number of OR-groups in the ANY bucket. A defensive bound so a
# crafted URL can't fan out into an unbounded AND-of-ORs query plan.
_MAX_ANY_GROUPS = 10

# candidates.search_doc — PG STORED generated column (migration 0126) holding the
# space-joined concatenation of every searchable candidate text field EXCEPT
# raw_cv_text (which keeps its own ix_candidates_cv_trgm) and notes (separate
# table). Backed by ix_candidates_search_doc_trgm (GIN pg_trgm) so a leading-
# wildcard ILIKE is an index scan, not a 47.6K-row seq scan. Referenced as a bare
# column — deliberately NOT mapped on the ORM entity so `select(Candidate)` never
# loads this duplicated text into every row of every candidate list response.
_SEARCH_DOC = column("search_doc", Text)


def _escape_like(value: str) -> str:
    """Escape LIKE wildcards so user input is treated literally."""
    return value.replace("\\", r"\\").replace("%", r"\%").replace("_", r"\_")


def _identity_expr() -> ColumnElement:
    """``name || ' ' || lastname || ' ' || email`` — the exact expression the
    GIN trigram index ``ix_candidates_identity_trgm`` (migration 0013) is built
    on. Used by the fuzzy (typo-tolerant) identity branch via the ``%`` operator,
    which consults ``pg_trgm.similarity_threshold`` (set per-request by the
    caller) and therefore uses that index instead of a seq-scan ``similarity()``
    filter.
    """
    return (
        func.coalesce(Candidate.name, "")
        + " "
        + func.coalesce(Candidate.lastname, "")
        + " "
        + func.coalesce(Candidate.email, "")
    )


def _phrase_match(phrase: str, *, fuzzy: bool = False) -> ColumnElement:
    """Indexable predicate: candidate matches ``phrase`` (case-insensitive
    substring) in ANY searchable field.

    Built as ``candidates.id IN (UNION of id-subqueries)`` so each branch drives
    its own GIN trigram index (Append of bitmap index scans) instead of a single
    OR-of-ILIKEs the planner can only satisfy with a full seq scan:
      • ``search_doc ILIKE``    → ix_candidates_search_doc_trgm (all non-CV cols),
      • ``raw_cv_text ILIKE``   → ix_candidates_cv_trgm,
      • ``notes.content ILIKE`` → ix_notes_content_trgm (candidate_id NOT NULL so
        the ``NOT IN`` form used by the NONE bucket can't hit the NULL trap).

    When ``fuzzy`` is set (simple ``?q=`` search, phrase ≥3 chars) a trigram-
    similarity branch on identity is unioned in via the ``%`` operator —
    preserving the old typo-tolerant identity match. The caller MUST set
    ``pg_trgm.similarity_threshold`` for the transaction first (see
    ``list_candidates``); the substring branches are unaffected by that GUC.
    """
    pattern = f"%{_escape_like(phrase)}%"
    branches = [
        select(Candidate.id).where(_SEARCH_DOC.ilike(pattern, escape="\\")),
        select(Candidate.id).where(Candidate.raw_cv_text.ilike(pattern, escape="\\")),
        select(Note.candidate_id).where(
            Note.candidate_id.is_not(None),
            Note.content.ilike(pattern, escape="\\"),
        ),
    ]
    if fuzzy:
        # self_group() forces parentheses around the `||` concatenation: in
        # PostgreSQL `%` binds tighter than `||`, so `a || b % c` would parse as
        # `a || (b % c)` (string || boolean → type error). `(a || b) % c` both
        # parses correctly AND matches ix_candidates_identity_trgm's expression.
        branches.append(
            select(Candidate.id).where(_identity_expr().self_group().op("%")(phrase))
        )
    return Candidate.id.in_(union(*branches))


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


def single_phrase_filter(
    phrase: str, *, fuzzy: bool = False
) -> Optional[ColumnElement]:
    """Build a WHERE clause for a single simple-search phrase.

    Used by the legacy `?q=...` parameter on GET /api/candidates to share
    the exact same field scope as the boolean `?q_all=...` path. Returns
    None when the phrase is too short to be useful — caller should skip
    the .where() in that case. ``fuzzy`` adds the typo-tolerant identity
    branch (see ``_phrase_match``).
    """
    cleaned = _clean([phrase])
    if not cleaned:
        return None
    return _phrase_match(cleaned[0], fuzzy=fuzzy)


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
