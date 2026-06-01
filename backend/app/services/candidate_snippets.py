"""Snippet extraction for the candidates list (Traffit parity).

Given a candidate row and the recruiter's search phrases, return a short
fragment of text around the first matching term — so the row can show
"why this candidate matched" without the user opening the drawer.

Resolution order mirrors `_SEARCHABLE_COLUMNS` priority:
    1. raw_cv_text (longest, most likely to contain context)
    2. ai_summary
    3. competence_category
    4. experience JSONB (cast to str — companies, roles, descriptions)
    5. skills JSONB
    6. tags JSONB
    7. education JSONB
    8. notes (looked up separately — passed in by the API layer)
    9. linkedin_current_title / linkedin_current_company
   10. name / lastname / email — last resort (identity matched via trigram
       rather than direct ILIKE; show the email as the explainer)

The function is intentionally cheap: pure-Python string ops, no DB I/O.
The API caller fetches notes in a single batched query for the page and
passes them in via `notes_by_candidate`.
"""

from __future__ import annotations

import json
from typing import Any, Iterable, Optional

from app.models.candidate import Candidate

# Total window around the matched term (chars on each side). 60 + match + 60
# ≈ 130-160 chars is what fits comfortably on one line in the candidates
# list row.
_SNIPPET_WINDOW = 60
_MAX_SNIPPET_LEN = 200


def _normalize_terms(terms: Iterable[Optional[str]]) -> list[str]:
    """Lowercase + strip + drop blanks + dedupe (case-insensitive)."""
    out: list[str] = []
    seen: set[str] = set()
    for t in terms:
        if not t:
            continue
        norm = t.strip().lower()
        if not norm or norm in seen:
            continue
        seen.add(norm)
        out.append(norm)
    return out


def _slice_around(haystack: str, idx: int, term_len: int) -> str:
    """Return a substring centered on `idx` with `_SNIPPET_WINDOW` chars
    of surrounding context, prefixed/suffixed with ellipsis when truncated."""
    start = max(0, idx - _SNIPPET_WINDOW)
    end = min(len(haystack), idx + term_len + _SNIPPET_WINDOW)
    snippet = haystack[start:end].strip()
    if start > 0:
        snippet = "…" + snippet
    if end < len(haystack):
        snippet = snippet + "…"
    # Collapse internal whitespace runs — JSON-cast fields often contain
    # newlines and tabs that bloat the display without adding value.
    snippet = " ".join(snippet.split())
    if len(snippet) > _MAX_SNIPPET_LEN:
        snippet = snippet[: _MAX_SNIPPET_LEN - 1] + "…"
    return snippet


def _find_term(haystack: Optional[str], terms: list[str]) -> Optional[tuple[int, int]]:
    """Find the FIRST term occurrence in `haystack`. Returns (index, term_len)
    or None. Lowercase compare so terms match regardless of original casing."""
    if not haystack:
        return None
    lower = haystack.lower()
    best: Optional[tuple[int, int]] = None
    for term in terms:
        idx = lower.find(term)
        if idx < 0:
            continue
        if best is None or idx < best[0]:
            best = (idx, len(term))
    return best


def _stringify(value: Any) -> Optional[str]:
    """Coerce JSONB / dict / list payloads to a flat string for ILIKE-style
    matching. Returns None for empty values so the caller can short-circuit."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, (list, dict)):
        try:
            return json.dumps(value, ensure_ascii=False)
        except (TypeError, ValueError):
            return str(value)
    return str(value)


def extract_snippet(
    candidate: Candidate,
    terms: list[str],
    notes_contents: Optional[list[str]] = None,
) -> Optional[str]:
    """Return a snippet for the candidate or None if no field matched.

    `terms` should already be normalized (lowercase, deduped) — call
    `_normalize_terms` once at the API layer and pass the result.

    `notes_contents` is the list of `Note.content` strings for this
    candidate; the API batches these in a single query for the whole
    page so we avoid N+1 here.
    """
    if not terms:
        return None

    # Priority-ordered list of (field_label_prefix, value) pairs. The
    # label appears in the snippet so the recruiter knows where the match
    # came from ("Notatka: ...", "CV: ..."). Empty prefix = no label.
    candidates_to_scan: list[tuple[str, Optional[str]]] = [
        ("CV", candidate.raw_cv_text),
        ("AI", candidate.ai_summary),
        ("Kategoria", candidate.competence_category),
        ("Doświadczenie", _stringify(candidate.experience)),
        ("Skills", _stringify(candidate.skills)),
        ("Tagi", _stringify(candidate.tags)),
        ("Wykształcenie", _stringify(candidate.education)),
        ("Języki", _stringify(candidate.languages)),
        ("Stanowisko LinkedIn", candidate.linkedin_current_title),
        ("Firma LinkedIn", candidate.linkedin_current_company),
        ("Lokalizacja", candidate.location),
        ("Telefon", candidate.phone),
        ("Email", candidate.email),
    ]

    for label, value in candidates_to_scan:
        match = _find_term(value, terms)
        if match is None:
            continue
        idx, term_len = match
        body = _slice_around(value or "", idx, term_len)
        return f"{label}: {body}" if label else body

    # Notes last — they sit in a separate table, so the API layer fetches
    # them and passes the raw content list in. Use the first matching note.
    if notes_contents:
        for note_content in notes_contents:
            match = _find_term(note_content, terms)
            if match is None:
                continue
            idx, term_len = match
            return "Notatka: " + _slice_around(note_content, idx, term_len)

    return None


def extract_search_terms(
    q: Optional[str],
    q_all: Optional[list[str]],
    q_any: Optional[list[str]],
    q_any_groups: Optional[list[list[str]]] = None,
) -> list[str]:
    """Combine all positive search inputs (q + q_all + q_any + q_any_groups)
    into a single deduped lowercase list. `q_none` is intentionally ignored —
    exclusion phrases shouldn't drive snippet highlighting."""
    parts: list[Optional[str]] = []
    if q:
        parts.append(q)
    if q_all:
        parts.extend(q_all)
    if q_any:
        parts.extend(q_any)
    if q_any_groups:
        for group in q_any_groups:
            parts.extend(group)
    return _normalize_terms(parts)
