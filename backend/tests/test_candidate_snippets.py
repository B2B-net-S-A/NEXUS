"""Unit tests for the candidates-list match snippet.

Pure functions — no DB, no HTTP fixture. Covers the two guarantees:
  1. the snippet is readable (HTML / Tiptap / JSONB flattened to plain text), and
  2. every searched word (q_all) appears in the snippet even when the matches
     live in different candidate fields.
"""

from __future__ import annotations

from app.models.candidate import Candidate
from app.services.candidate_snippets import (
    extract_search_terms,
    extract_snippet,
)
from app.services.text_cleaning import clean_rich_text, flatten_json_text


def _cand(**overrides) -> Candidate:
    """In-memory candidate — instantiation needs no session; the snippet code
    only reads attributes."""
    return Candidate(**overrides)


# ── clean_rich_text ─────────────────────────────────────────────────────────


def test_clean_rich_text_strips_word_html_and_entities():
    raw = (
        '<p class="MsoNormal"><strong>Możliwość pracy z biura:</strong>&nbsp;'
        "3 dni w tyg/Warszawa</p>"
    )
    out = clean_rich_text(raw)
    assert "<" not in out and ">" not in out
    assert "&nbsp;" not in out
    assert out == "Możliwość pracy z biura: 3 dni w tyg/Warszawa"


def test_clean_rich_text_unwraps_tiptap_json_and_mentions():
    doc = (
        '{"type":"doc","content":[{"type":"paragraph","content":['
        '{"type":"text","text":"Dziś $$user_37$$ ustalił rate"}]}]}'
    )
    assert clean_rich_text(doc) == "Dziś @user ustalił rate"


def test_clean_rich_text_malformed_json_falls_back_to_raw():
    assert clean_rich_text("{broken") == "{broken"
    assert clean_rich_text("") == ""
    assert clean_rich_text(None) == ""


# ── flatten_json_text ───────────────────────────────────────────────────────


def test_flatten_json_text_recurses_without_punctuation():
    exp = [
        {
            "company": "Acme",
            "role": "Java Developer",
            "highlights": ["Spring Boot", "REST API"],
        },
    ]
    flat = flatten_json_text(exp)
    assert "{" not in flat and '"' not in flat and "[" not in flat
    for token in ("Acme", "Java Developer", "Spring Boot", "REST API"):
        assert token in flat


def test_flatten_json_text_ignores_bool_and_none():
    assert flatten_json_text({"a": None, "b": True, "c": "keep"}) == "keep"
    assert flatten_json_text(None) == ""


# ── extract_search_terms ────────────────────────────────────────────────────


def test_extract_search_terms_dedupes_and_lowercases():
    terms = extract_search_terms(
        "Senior", ["Java", "java", "  "], ["React"], [["Angular"]]
    )
    assert terms == ["senior", "java", "react", "angular"]


# ── extract_snippet: the reported bug — unreadable note ─────────────────────


def test_snippet_from_html_note_is_readable():
    note = (
        '<p class="MsoNormal"><strong>Preferencje:</strong>&nbsp;3 dni w tyg/'
        'Warszawa</p>\n<p class="MsoNormal"><strong>Narodowość:</strong>&nbsp;PL</p>'
    )
    terms = extract_search_terms(None, ["Warszawa"], None)
    snip = extract_snippet(_cand(), terms, notes_contents=[note])
    assert snip is not None
    assert snip.startswith("Notatka: ")
    assert "<" not in snip and "&nbsp;" not in snip
    assert "Warszawa" in snip


# ── extract_snippet: every q_all word present ───────────────────────────────


def test_snippet_covers_all_terms_from_single_cv():
    cv = (
        "Senior Java developer. Stack: Spring Boot, REST API, Angular and React. "
        "DB: Oracle 19c. Based in Warszawa, hybrid."
    )
    terms = extract_search_terms(
        None,
        ["Java", "Oracle", "Angular", "React", "Spring Boot", "REST API", "Warszawa"],
        None,
    )
    snip = extract_snippet(_cand(raw_cv_text=cv), terms)
    assert snip is not None
    low = snip.lower()
    for term in terms:
        assert term in low, f"missing term: {term!r}"


def test_snippet_covers_terms_spread_across_fields():
    terms = extract_search_terms(None, ["Java", "Oracle", "Warszawa"], None)
    cand = _cand(
        raw_cv_text="Backend engineer, 8 lat Java.",
        skills=["Java", "Oracle", "PL/SQL"],
        location="Warszawa, mazowieckie",
    )
    snip = extract_snippet(cand, terms)
    assert snip is not None
    low = snip.lower()
    for term in terms:
        assert term in low, f"missing term: {term!r}"
    # Field labels tell the recruiter where each match came from.
    assert "CV:" in snip


def test_snippet_covers_term_only_in_city_or_engagement_notes():
    # `city` and `engagement_notes` are in the DB search_doc but were previously
    # absent from the snippet scan — a q_all term matching only there must still
    # surface.
    terms = extract_search_terms(None, ["Kraków", "Golang"], None)
    cand = _cand(city="Kraków", engagement_notes="Zna Golang z projektów fintech.")
    snip = extract_snippet(cand, terms)
    assert snip is not None
    low = snip.lower()
    assert "kraków" in low and "golang" in low


def test_snippet_flattens_jsonb_experience_readably():
    exp = [
        {
            "company": "Acme",
            "role": "Java Developer",
            "description": "Built REST API on Spring Boot",
        }
    ]
    terms = extract_search_terms(None, ["Spring Boot"], None)
    snip = extract_snippet(_cand(experience=exp), terms)
    assert snip is not None
    assert "{" not in snip and '"' not in snip
    assert "spring boot" in snip.lower()


def test_snippet_none_when_no_field_matches():
    cand = _cand(raw_cv_text="nothing relevant here")
    assert extract_snippet(cand, extract_search_terms(None, ["Kotlin"], None)) is None


def test_snippet_empty_terms_returns_none():
    assert extract_snippet(_cand(raw_cv_text="Java"), []) is None


def test_snippet_coverage_survives_length_cap():
    # Two terms separated by long filler across two fields would blow the length
    # cap; the safety net re-appends any word truncated away.
    filler = "x" * 350
    terms = extract_search_terms(None, ["alpha", "omega"], None)
    cand = _cand(raw_cv_text=f"alpha {filler}", engagement_notes=f"{filler} omega")
    snip = extract_snippet(cand, terms)
    assert snip is not None
    low = snip.lower()
    assert "alpha" in low and "omega" in low


def test_snippet_coalesces_nearby_hits_into_one_window():
    # Terms close together in the same field share one window (one label), not
    # a fragment per term.
    cv = "Expert in Java and Oracle, hands-on daily."
    terms = extract_search_terms(None, ["Java", "Oracle"], None)
    snip = extract_snippet(_cand(raw_cv_text=cv), terms)
    assert snip is not None
    assert snip.count("CV:") == 1
    assert snip.count("·") == 0  # single window, no separator
