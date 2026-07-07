"""Snippet extraction for the candidates list (Traffit parity).

Given a candidate row and the recruiter's search phrases, return a short,
**readable** fragment that explains *why this candidate matched* — so the row
can show the match reason without the user opening the drawer.

Two guarantees drive the design (both requested by recruiters):

1. **Readable.** The source text is cleaned first (`clean_rich_text`): notes are
   stored as Tiptap HTML/JSON (legacy Word paste → `<p class="MsoNormal">`,
   `&nbsp;`, `$$user_NN$$` markers) and JSONB columns are structured — raw, both
   render as unreadable markup. We flatten to plain text before slicing.

2. **Every searched word is present.** With `q_all` (all phrases must match) the
   matched terms can live in *different* fields (e.g. "Warszawa" in `location`,
   "Java"/"Spring Boot" in `raw_cv_text`, "Oracle" in `skills`). Instead of a
   single window around the *first* match, we scan fields in priority order and
   accumulate a compact window around every not-yet-covered term until all of
   them are covered. Nearby hits in the same field coalesce into one window, so
   a CV listing several requirements collapses to one clean fragment.

The corpus mirrors the DB search scope (``search_doc`` columns + ``raw_cv_text``
+ ``notes.content``, see `advanced_candidate_search`) so any term that matched
in the DB is findable here.

The function is intentionally cheap: pure-Python string ops, no DB I/O. The API
caller fetches notes in a single batched query for the page and passes them in
via ``notes_contents``.
"""

from __future__ import annotations

from typing import Iterable, Optional

from app.models.candidate import Candidate
from app.services.text_cleaning import clean_rich_text, flatten_json_text

# Context kept on each side of a matched span. term + 2×_CONTEXT ≈ 90-110 chars
# per window — enough to read the surrounding phrase, short enough that several
# windows fit under the 3-line clamp in the candidates list row.
_CONTEXT = 42
# Two matched terms in the same field whose gap is ≤ this many chars collapse
# into a single window spanning both (with shared context) instead of two
# near-duplicate fragments.
_MERGE_GAP = 90
# Hard cap on a single field's rendered window.
_MAX_WINDOW_LEN = 220
# Overall cap on the assembled snippet. Generous so a multi-term (q_all) match
# keeps every word; the row clamps the display visually.
_MAX_SNIPPET_LEN = 400


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


def _coalesce(spans: list[tuple[int, int]], gap: int) -> list[tuple[int, int]]:
    """Merge overlapping / near-adjacent ``(start, end)`` spans (≤ ``gap`` apart)
    into minimal covering spans. ``spans`` must be sorted by start."""
    merged: list[tuple[int, int]] = []
    for start, end in spans:
        if merged and start - merged[-1][1] <= gap:
            prev_start, prev_end = merged[-1]
            merged[-1] = (prev_start, max(prev_end, end))
        else:
            merged.append((start, end))
    return merged


def _render_window(text: str, span_start: int, span_end: int) -> str:
    """Return ``text`` around ``[span_start, span_end)`` with ``_CONTEXT`` chars
    of surrounding context, ellipsis-marked when truncated and whitespace-
    collapsed. The matched span sits near the centre, so it always survives the
    per-window length cap."""
    start = max(0, span_start - _CONTEXT)
    end = min(len(text), span_end + _CONTEXT)
    fragment = text[start:end].strip()
    if start > 0:
        fragment = "…" + fragment
    if end < len(text):
        fragment = fragment + "…"
    fragment = " ".join(fragment.split())
    if len(fragment) > _MAX_WINDOW_LEN:
        fragment = fragment[: _MAX_WINDOW_LEN - 1].rstrip() + "…"
    return fragment


def _field_corpus(
    candidate: Candidate,
    notes_contents: Optional[list[str]],
) -> list[tuple[str, str]]:
    """Priority-ordered ``(label, cleaned_text)`` blocks to scan.

    Label prefixes the window so the recruiter knows where the match came from
    ("CV: …", "Umiejętności: …"). Content-rich fields come first; bare identity
    fields (phone / email / name) are last-resort explainers. The set covers the
    same columns the DB search matches on, so every ``q_all`` term is findable.
    """
    blocks: list[tuple[str, str]] = [
        ("CV", clean_rich_text(candidate.raw_cv_text)),
        ("AI", clean_rich_text(candidate.ai_summary)),
        ("Kategoria", clean_rich_text(candidate.competence_category)),
        ("Uwagi", clean_rich_text(candidate.engagement_notes)),
        ("Doświadczenie", clean_rich_text(flatten_json_text(candidate.experience))),
        ("Umiejętności", clean_rich_text(flatten_json_text(candidate.skills))),
        ("Tagi", clean_rich_text(flatten_json_text(candidate.tags))),
        ("Wykształcenie", clean_rich_text(flatten_json_text(candidate.education))),
        ("Języki", clean_rich_text(flatten_json_text(candidate.languages))),
        ("Stanowisko LinkedIn", clean_rich_text(candidate.linkedin_current_title)),
        ("Firma LinkedIn", clean_rich_text(candidate.linkedin_current_company)),
        ("Lokalizacja", clean_rich_text(candidate.location)),
        ("Miasto", clean_rich_text(candidate.city)),
    ]
    # Notes sit in a separate table — the API layer batches them and passes the
    # raw content list in. Each cleaned note is its own scannable block.
    if notes_contents:
        for note in notes_contents:
            blocks.append(("Notatka", clean_rich_text(note)))
    # Identity fields last: only surfaced when nothing richer explains the match.
    blocks.extend(
        [
            ("Telefon", clean_rich_text(candidate.phone)),
            ("Email", clean_rich_text(candidate.email)),
            (
                "Kandydat",
                clean_rich_text(f"{candidate.name or ''} {candidate.lastname or ''}"),
            ),
        ]
    )
    return blocks


def extract_snippet(
    candidate: Candidate,
    terms: list[str],
    notes_contents: Optional[list[str]] = None,
) -> Optional[str]:
    """Return a readable snippet covering every matched search term, or None.

    ``terms`` should already be normalized (lowercase, deduped) — call
    ``_normalize_terms`` once at the API layer and pass the result.

    ``notes_contents`` is the list of ``Note.content`` strings for this
    candidate; the API batches these in a single query for the whole page so we
    avoid N+1 here.
    """
    if not terms:
        return None

    covered: set[str] = set()
    rendered: list[str] = []

    for label, text in _field_corpus(candidate, notes_contents):
        if covered.issuperset(terms):
            break
        if not text:
            continue
        want = [t for t in terms if t not in covered]
        lower = text.lower()
        hits: list[tuple[int, int, str]] = []
        for term in want:
            idx = lower.find(term)
            if idx >= 0:
                hits.append((idx, idx + len(term), term))
        if not hits:
            continue
        hits.sort(key=lambda h: h[0])
        spans = _coalesce([(s, e) for s, e, _ in hits], _MERGE_GAP)
        for i, (span_start, span_end) in enumerate(spans):
            window = _render_window(text, span_start, span_end)
            rendered.append(f"{label}: {window}" if label and i == 0 else window)
        covered.update(term for _, _, term in hits)

    if not rendered:
        return None

    snippet = " · ".join(rendered)
    if len(snippet) > _MAX_SNIPPET_LEN:
        snippet = snippet[: _MAX_SNIPPET_LEN - 1].rstrip() + "…"

    # Coverage safety net: if the length cap truncated away a term we located,
    # re-append the bare word(s) so the invariant "every searched word appears
    # in the snippet" holds regardless of where the match landed.
    lowered = snippet.lower()
    missing = [t for t in terms if t in covered and t not in lowered]
    if missing:
        snippet = snippet.rstrip("… ").rstrip() + " · " + ", ".join(missing)

    return snippet


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
