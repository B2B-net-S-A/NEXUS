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

Performance (2026-06-23): the substring path above stayed slow for COMMON terms.
pg_trgm GIN is lossy for ``LIKE``, so the ``raw_cv_text ILIKE`` branch re-reads
and DETOASTS every CV the index flags; a common keyword flags thousands of rows
(``java`` ≈ 17K = 34% of the base), so it was thousands of multi-KB CV detoasts
per request — measured 3.4s (``java|selenium``) up to 26.9s (``java`` page 50)
cold. Fix: plain alphanumeric words (≥3 chars) now route through a word-PREFIX
``tsvector`` match (``search_fts @@ to_tsquery('simple', 'phrase:*')`` →
``ix_candidates_search_fts``, migration 0143), which is evaluated against the
compact stored tsvector and never detoasts the CV. Short / special-char fragments
(``c++``, ``c#``, ``.net``, ``node.js``, multi-word phrases) keep the exact
trigram-substring path above. Semantics shift for the FTS path only: matching is
word-PREFIX (token-aware) rather than arbitrary substring — ``jav`` → ``java``
and ``java`` → ``javascript`` still match; only rare mid-word substrings
(``ava`` → ``java``) are dropped.
"""

from __future__ import annotations

from typing import Optional

from sqlalchemy import Text, and_, column, func, not_, or_, select, union
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.sql import ColumnElement

from app.models.candidate import Candidate
from app.models.note import Note

_MAX_PHRASES_PER_BUCKET = 20
_MIN_PHRASE_LEN = 2
# Cap on the number of OR-groups in the ANY bucket. A defensive bound so a
# crafted URL can't fan out into an unbounded AND-of-ORs query plan.
_MAX_ANY_GROUPS = 10

# Phrases at/above this length that are a single plain alphanumeric token route
# through the fast FTS word-prefix path (see `_fts_eligible` / `_phrase_match`).
_FTS_MIN_WORD_LEN = 3
# Postgres text-search config used for both the stored tsvector (migration 0143)
# and the query side. 'simple' = lowercase + tokenize only (no stemming, no
# stopwords) → predictable tech tokens (`java` → `java`, never stemmed away).
_FTS_CONFIG = "simple"

# candidates.search_doc — PG STORED generated column (migration 0126) holding the
# space-joined concatenation of every searchable candidate text field EXCEPT
# raw_cv_text (which keeps its own ix_candidates_cv_trgm) and notes (separate
# table). Backed by ix_candidates_search_doc_trgm (GIN pg_trgm) so a leading-
# wildcard ILIKE is an index scan, not a 47.6K-row seq scan. Referenced as a bare
# column — deliberately NOT mapped on the ORM entity so `select(Candidate)` never
# loads this duplicated text into every row of every candidate list response.
_SEARCH_DOC = column("search_doc", Text)

# candidates.search_fts — STORED tsvector (migration 0143) over the same field
# scope as search_doc PLUS raw_cv_text (capped), backed by ix_candidates_search_fts
# (GIN). `@@` is evaluated against this compact tsvector, so the keyword filter
# never detoasts the multi-KB CV text the way the lossy pg_trgm substring recheck
# does — that detoast was the 3-27s seen for common terms. Bare column (not ORM-
# mapped) so `select(Candidate)` never ships the tsvector in list responses.
_SEARCH_FTS = column("search_fts", TSVECTOR)


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


def _fts_eligible(phrase: str) -> bool:
    """True when ``phrase`` should route through the fast FTS word-prefix path
    instead of trigram-substring.

    Eligible = a single plain alphanumeric token of ``_FTS_MIN_WORD_LEN``+ chars
    (``java``, ``selenium``, ``python``, ``łukasz``). Anything with whitespace or
    special chars (``c++``, ``c#``, ``.net``, ``node.js``, ``senior java``) or
    shorter keeps exact substring semantics via the trigram path — the FTS parser
    would split those awkwardly, and short fragments are better matched as
    substrings. ``str.isalnum()`` is unicode-aware, so accented/Polish tokens
    qualify.
    """
    return len(phrase) >= _FTS_MIN_WORD_LEN and phrase.isalnum()


def _phrase_match(phrase: str, *, fuzzy: bool = False) -> ColumnElement:
    """Indexable predicate: candidate matches ``phrase`` in ANY searchable field.

    Built as ``candidates.id IN (UNION of id-subqueries)`` so each branch drives
    its own index (Append of bitmap scans) instead of a single OR the planner can
    only satisfy with a full seq scan. Two routes (see ``_fts_eligible``):

    FTS word-prefix (plain alphanumeric word, ≥3 chars) — the fast path:
      • ``search_fts @@ to_tsquery('simple', 'phrase:*')`` → ix_candidates_search_fts.
        The GIN tsvector match reads the compact stored tsvector and never
        detoasts the multi-KB ``raw_cv_text`` the way the lossy pg_trgm recheck
        did (that detoast was the 3-27s for common terms — migration 0143).
        ``:*`` is a word-PREFIX match so ``jav`` still finds ``java`` (incremental
        ⌘K typing) and ``java`` still finds ``javascript`` (word-prefix); only
        rare mid-word substrings (``ava`` → ``java``) are dropped.
      • ``notes.content ILIKE`` → ix_notes_content_trgm. Notes stay substring
        (separate, smaller table; recruiter prose where substring is reasonable).

    Substring fallback (short / non-alphanumeric fragment):
      • ``search_doc ILIKE``    → ix_candidates_search_doc_trgm (all non-CV cols),
      • ``raw_cv_text ILIKE``   → ix_candidates_cv_trgm,
      • ``notes.content ILIKE`` → ix_notes_content_trgm.

    The ``notes.candidate_id NOT NULL`` guard keeps the ``NOT IN`` form used by
    the NONE bucket off the NULL trap.

    When ``fuzzy`` is set (simple ``?q=`` search, phrase ≥3 chars) a trigram-
    similarity branch on identity is unioned in via the ``%`` operator —
    preserving typo-tolerant identity matching. The caller MUST set
    ``pg_trgm.similarity_threshold`` for the transaction first (see
    ``list_candidates``); the other branches are unaffected by that GUC.
    """
    pattern = f"%{_escape_like(phrase)}%"
    notes_branch = select(Note.candidate_id).where(
        Note.candidate_id.is_not(None),
        Note.content.ilike(pattern, escape="\\"),
    )
    if _fts_eligible(phrase):
        # `phrase` is guaranteed alphanumeric, so `phrase + ":*"` is always valid
        # tsquery syntax (a single prefix-matched lexeme) — no operators to inject.
        tsquery = func.to_tsquery(_FTS_CONFIG, phrase + ":*")
        branches = [
            select(Candidate.id).where(_SEARCH_FTS.op("@@")(tsquery)),
            notes_branch,
        ]
    else:
        branches = [
            select(Candidate.id).where(_SEARCH_DOC.ilike(pattern, escape="\\")),
            select(Candidate.id).where(
                Candidate.raw_cv_text.ilike(pattern, escape="\\")
            ),
            notes_branch,
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
