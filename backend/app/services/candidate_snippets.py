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

from typing import Any, Iterable, Iterator, Optional

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
) -> Iterator[tuple[str, str]]:
    """Priority-ordered ``(label, cleaned_text)`` blocks to scan.

    Label prefixes the window so the recruiter knows where the match came from
    ("CV: …", "Umiejętności: …"). Content-rich fields come first; bare identity
    fields (phone / email / name) are last-resort explainers. The set covers the
    same columns the DB search matches on, so every ``q_all`` term is findable.

    Generator (runda 7, R7-N10-5): ``extract_snippet`` przerywa, gdy pokryje
    wszystkie słowa — reszta pól (z notatkami) nie jest już czyszczona.
    """
    raw_blocks: list[tuple[str, Any]] = [
        ("CV", lambda: candidate.raw_cv_text),
        ("AI", lambda: candidate.ai_summary),
        ("Kategoria", lambda: candidate.competence_category),
        ("Uwagi", lambda: candidate.engagement_notes),
        ("Doświadczenie", lambda: flatten_json_text(candidate.experience)),
        ("Umiejętności", lambda: flatten_json_text(candidate.skills)),
        ("Tagi", lambda: flatten_json_text(candidate.tags)),
        ("Wykształcenie", lambda: flatten_json_text(candidate.education)),
        ("Języki", lambda: flatten_json_text(candidate.languages)),
        ("Stanowisko LinkedIn", lambda: candidate.linkedin_current_title),
        ("Firma LinkedIn", lambda: candidate.linkedin_current_company),
        ("Lokalizacja", lambda: candidate.location),
        ("Miasto", lambda: candidate.city),
    ]
    for label, getter in raw_blocks:
        yield label, clean_rich_text(getter())
    # Notes sit in a separate table — the API layer batches them and passes the
    # raw content list in. Each cleaned note is its own scannable block.
    for note in notes_contents or []:
        yield "Notatka", clean_rich_text(note)
    # Identity fields last: only surfaced when nothing richer explains the match.
    yield "Telefon", clean_rich_text(candidate.phone)
    yield "Email", clean_rich_text(candidate.email)
    yield (
        "Kandydat",
        clean_rich_text(f"{candidate.name or ''} {candidate.lastname or ''}"),
    )


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


# ═══════════════════════════════════════════════════════════════════════════
# v2: wszystkie trafienia, osobno dla każdego pola (Traffit parity, 22.09.2026)
# ═══════════════════════════════════════════════════════════════════════════
#
# Traffit pod każdym wynikiem pokazuje każde pole, w którym padło szukane słowo
# („Treść CV: …”, „Technologie: …”, „Stanowisko: …”), z pogrubieniem. Stary
# wycinek NEXUSA brał JEDNO okno z pierwszego pola i szukał podłańcucha, więc
# „java” pogrubiało „Java” w „JavaScript”. Tu: to samo dopasowanie co filtr
# (`keyword_terms` — całe słowa, gwiazdka), zakres pola i zakresy pogrubień
# liczone na serwerze (front nie powtarza reguły).

_FIELD_WINDOWS = 2
_MAX_FIELDS = 5

_SCOPE_FIELDS = {
    "cv": {"Treść CV"},
    "title": {"Stanowisko"},
    "skills": {"Umiejętności"},
    "notes": {"Notatka"},
}


def _experience_roles(candidate: Candidate) -> str:
    exp = candidate.experience
    if not isinstance(exp, list):
        return ""
    roles = [
        str(item.get("role")).strip()
        for item in exp
        if isinstance(item, dict) and item.get("role")
    ]
    return " · ".join(r for r in roles if r)


def _structured_corpus(
    candidate: Candidate, notes_contents: Optional[list[str]]
) -> Iterator[tuple[str, Any]]:
    """Pola korpusu słów kluczowych (``keyword_corpus``), każde osobno.

    Te same pola co wyszukiwanie — bez podsumowania AI, kluczy i poziomów
    JSON-ów — inaczej wycinek pokazywałby trafienie, po którym osoba wcale
    nie została znaleziona (albo nie pokazywał tego, po którym została).

    Runda 7 (R7-N10-5): generator SUROWYCH wartości — wołający czyści pole
    (``clean_rich_text``) dopiero wtedy, gdy zakres je dopuszcza i nie ma
    jeszcze ``_MAX_FIELDS`` pól. Dawniej cały korpus (z setkami notatek-maili)
    był czyszczony z góry dla każdej osoby na stronie.
    """
    from app.services import keyword_corpus as kc

    def attr(name: str) -> Any:
        return getattr(candidate, name, None)

    yield "Treść CV", attr("raw_cv_text")
    yield "Stanowisko", kc.title_text(candidate, _experience_roles(candidate))
    yield "Umiejętności", kc.skills_text(candidate)
    yield "Doświadczenie", kc.json_text(attr("experience"), kc.EXPERIENCE_KEYS)
    yield "O sobie", attr("profile_about")
    yield "Certyfikaty", kc.traffit_value(candidate, "traffit_certificates")
    yield (
        "Poprzedni pracodawcy",
        kc.traffit_value(candidate, "traffit_previous_employers"),
    )
    yield "Uwagi", attr("engagement_notes")
    yield "Tagi", kc.json_text(attr("tags"), kc.TAG_KEYS)
    yield (
        "Wykształcenie",
        " · ".join(
            p
            for p in (
                kc.json_text(attr("education"), kc.EDUCATION_KEYS),
                kc.traffit_value(candidate, "traffit_education"),
            )
            if p
        ),
    )
    yield "Języki", kc.json_text(attr("languages"), kc.LANGUAGE_KEYS)
    yield (
        "LinkedIn",
        " · ".join(
            p
            for p in (
                attr("linkedin_current_title"),
                attr("linkedin_current_company"),
            )
            if p
        ),
    )
    yield "Lokalizacja", attr("location") or attr("city")
    yield "Narodowość", kc.traffit_value(candidate, "traffit_nationality")
    for note in notes_contents or []:
        yield "Notatka", note
    yield "Email", attr("email")
    yield "Kandydat", f"{attr('name') or ''} {attr('lastname') or ''}"


def _term_patterns(terms: list[str], whole_words: bool) -> list:
    import re

    from app.services.keyword_terms import parse_keyword, py_regex

    patterns = []
    for raw in terms:
        term = parse_keyword(raw)
        if term is None:
            continue
        if whole_words:
            patterns.append(py_regex(term))
        else:
            patterns.append(re.compile(re.escape(term.text), re.IGNORECASE))
    return patterns


def _folded_term_patterns(terms: list[str]) -> list:
    """Wzorce do tekstu złożonego (``keyword_corpus.fold_text``) — przy
    korpusie złożonym filtr znajduje „Kraków” dla „krakow”, więc wycinek musi
    go też pokazać. Pusta lista, gdy ścieżka złożona jest wyłączona."""
    from app.services import keyword_corpus
    from app.services.keyword_terms import KeywordTerm, parse_keyword, py_regex

    if not keyword_corpus.folded_search_enabled():
        return []
    patterns = []
    for raw in terms:
        term = parse_keyword(raw)
        if term is None:
            continue
        folded = keyword_corpus.fold_text(term.text)
        patterns.append(
            py_regex(
                KeywordTerm(
                    raw=term.raw,
                    text=" ".join(folded.split()),
                    open_end=term.open_end,
                    open_start=term.open_start,
                )
            )
        )
    return patterns


def extract_field_snippets(
    candidate: Candidate,
    terms: list[str],
    notes_contents: Optional[list[str]] = None,
    *,
    whole_words: bool = True,
    scope: str = "all",
) -> list[dict]:
    """Lista ``{"field", "text", "highlights": [[start, end], …]}`` — każde pole
    z trafieniem (najwyżej ``_MAX_FIELDS``), w każdym do ``_FIELD_WINDOWS``
    okien. ``highlights`` to zakresy znaków w ``text`` do pogrubienia."""
    patterns = _term_patterns(terms, whole_words)
    if not patterns:
        return []
    folded_patterns = _folded_term_patterns(terms) if whole_words else []
    allowed = _SCOPE_FIELDS.get(scope)
    out: list[dict] = []
    for label, raw in _structured_corpus(candidate, notes_contents):
        if len(out) >= _MAX_FIELDS:
            break
        if not raw or (allowed is not None and label not in allowed):
            continue
        text = clean_rich_text(raw)
        if not text:
            continue
        found: set[tuple[int, int]] = set()
        for pattern in patterns:
            found.update((m.start(), m.end()) for m in pattern.finditer(text))
        if folded_patterns:
            from app.services.keyword_corpus import fold_text_with_offsets

            # Pozycje w tekście złożonym przez mapę na oryginał (R7-X3-4).
            folded_text, starts, ends = fold_text_with_offsets(text)
            for pattern in folded_patterns:
                found.update(
                    (starts[m.start()], ends[m.end() - 1])
                    for m in pattern.finditer(folded_text)
                    if m.end() > m.start()
                )
        if not found:
            continue
        spans = sorted(found)
        windows = _coalesce(spans, _MERGE_GAP)[:_FIELD_WINDOWS]
        pieces: list[str] = []
        highlights: list[list[int]] = []
        for w_start, w_end in windows:
            start = max(0, w_start - _CONTEXT)
            end = min(len(text), max(w_end + _CONTEXT, start + 1))
            if end - start > _MAX_WINDOW_LEN:
                end = start + _MAX_WINDOW_LEN
            prefix = "…" if start > 0 else ""
            suffix = "…" if end < len(text) else ""
            offset = sum(len(p) for p in pieces) + (3 * len(pieces)) + len(prefix)
            chunk = text[start:end]
            for s, e in spans:
                if s >= start and e <= end:
                    highlights.append([offset + s - start, offset + e - start])
            pieces.append(prefix + chunk + suffix)
        joined = " · ".join(pieces)
        # Odstępy z CV (nowe linie, taby) — jedna linia, zakresy przeliczone.
        normalized, mapping = _collapse_whitespace(joined)
        units = _utf16_positions(normalized)
        out.append(
            {
                "field": label,
                "text": normalized,
                # Zakresy w jednostkach UTF-16 — tak liczy `String.slice` we
                # froncie; emoji przed trafieniem przesuwałoby pogrubienie.
                "highlights": [
                    [units[mapping[s]], units[mapping[e - 1] + 1]]
                    for s, e in highlights
                ],
            }
        )
    return out


def _utf16_positions(text: str) -> list[int]:
    """``positions[i]`` = pozycja znaku ``i`` w jednostkach UTF-16 (długość
    ``len(text) + 1`` — ostatni element to długość całego tekstu)."""
    positions = [0]
    for ch in text:
        positions.append(positions[-1] + (2 if ord(ch) > 0xFFFF else 1))
    return positions


def _collapse_whitespace(text: str) -> tuple[str, list[int]]:
    """Zwija odstępy do pojedynczej spacji; ``mapping[i]`` = nowa pozycja
    znaku ``i`` (znaki zwinięte wskazują na zachowaną spację)."""
    result: list[str] = []
    mapping: list[int] = []
    prev_space = False
    for ch in text:
        if ch.isspace():
            if prev_space:
                mapping.append(len(result) - 1)
                continue
            result.append(" ")
            prev_space = True
        else:
            result.append(ch)
            prev_space = False
        mapping.append(len(result) - 1)
    return "".join(result), mapping


def snippets_as_text(snippets: list[dict]) -> Optional[str]:
    """Stary kształt ``match_snippet`` (jeden napis) z listy pól."""
    if not snippets:
        return None
    text = " · ".join(f"{s['field']}: {s['text']}" for s in snippets)
    if len(text) > _MAX_SNIPPET_LEN:
        text = text[: _MAX_SNIPPET_LEN - 1].rstrip() + "…"
    return text
