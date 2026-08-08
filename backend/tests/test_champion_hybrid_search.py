"""The Champion's recommended searches must be able to reach the vector index.

`/api/search/candidates` takes the BM25 + dense + rerank path only when BOTH
`search_mode == "hybrid"` and a non-empty `q` are present. The whitelist the
LLM may emit had neither, so the single feature that turns a Champion Profile
into a candidate search was — by construction — the only surface in the product
that never touched the 47 921 candidate vectors maintained for exactly this.

DB-free.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.candidate_search import CandidateSearchRequest
from app.schemas.champion import (
    RecommendedSearchParams,
    RecommendedSearchParamsIn,
)
from app.services.candidate_column_coverage import ColumnCoverage


# ── Reaching the semantic path ───────────────────────────────────────────────


def test_params_carry_the_two_fields_hybrid_retrieval_requires():
    params = RecommendedSearchParams(q="senior backend Java, sektor bankowy")
    assert params.q
    assert params.search_mode == "hybrid"


def test_hybrid_is_the_default_mode():
    """The request schema defaults to "boolean"; a Champion search that forgot
    to say otherwise would silently fall back to keyword matching."""
    assert RecommendedSearchParams().search_mode == "hybrid"
    assert CandidateSearchRequest().search_mode == "boolean"


def test_approved_search_survives_the_round_trip_into_a_saved_search():
    """`model_dump(exclude_none=True)` is what gets stored as SavedSearch.filters
    and spread into a CandidateSearchRequest — both fields must come through."""
    params = RecommendedSearchParams(q="tester manualny, bankowość", search_mode="hybrid")
    dumped = params.model_dump(exclude_none=True)
    assert dumped["q"]
    assert dumped["search_mode"] == "hybrid"
    req = CandidateSearchRequest(**dumped)
    assert req.search_mode == "hybrid" and req.q


def test_missing_q_degrades_to_boolean_rather_than_erroring():
    """No `q` means no semantic leg — that must be a quiet fallback, not a 500."""
    dumped = RecommendedSearchParams().model_dump(exclude_none=True)
    assert "q" not in dumped
    req = CandidateSearchRequest(**dumped)
    assert req.q is None  # endpoint's `use_hybrid` guard is `and bool(q_text)`


# ── Experience filter is no longer emittable ─────────────────────────────────


def test_llm_cannot_emit_the_experience_filter_any_more():
    """Measured on prod: an AI-proposed "2-6 years" chip cut a relevant pool of
    11 091 to 45, because the column is filled for 1.2% of rows. The filter
    itself is now NULL-tolerant, but the model still should not reach for a
    field that describes almost nobody."""
    with pytest.raises(ValidationError):
        RecommendedSearchParamsIn.model_validate(
            {"q": "tester", "experience_years_min": 2}
        )


# ── Ingest vs storage ────────────────────────────────────────────────────────


def test_ingest_schema_rejects_an_invented_filter():
    with pytest.raises(ValidationError):
        RecommendedSearchParamsIn.model_validate({"q": "x", "salary_max": 200})


def test_storage_schema_tolerates_fields_written_by_an_older_prompt():
    """Proposals already sitting in `jobs.champion_profile` JSONB carry
    `experience_years_min` from prompt v1. Reading them must not explode —
    only *fresh* LLM output is held to the strict shape."""
    params = RecommendedSearchParams.model_validate(
        {"q": "tester", "experience_years_min": 2, "skills_must": ["Testing"]}
    )
    assert params.q == "tester"
    assert params.skills_must == ["Testing"]
    assert not hasattr(params, "experience_years_min")


def test_is_empty_counts_a_semantic_query_as_content():
    """A proposal whose only filter is `q` is a perfectly good hybrid search;
    treating it as empty would drop exactly the strategies we now want most."""
    assert RecommendedSearchParams().is_empty()
    assert RecommendedSearchParams(q="   ").is_empty()
    assert not RecommendedSearchParams(q="senior Java").is_empty()


# ── List caps mirror the request schema ──────────────────────────────────────


@pytest.mark.parametrize(
    "field,cap",
    [
        ("q_all", 20),
        ("q_none", 20),
        ("skills_must", 20),
        ("skills_any", 20),
        ("skills_none", 20),
        ("location_cities", 20),
    ],
)
def test_list_caps_match_the_request_schema(field, cap):
    """Without matching caps the proposal stores fine and then 422s the moment
    a recruiter clicks it — an error surfacing three steps from its cause."""
    ok = {field: [f"x{i}" for i in range(cap)], "q": "x"}
    RecommendedSearchParamsIn.model_validate(ok)

    too_many = {field: [f"x{i}" for i in range(cap + 1)], "q": "x"}
    with pytest.raises(ValidationError):
        RecommendedSearchParamsIn.model_validate(too_many)


def test_q_length_cap_matches_the_request_schema():
    RecommendedSearchParamsIn.model_validate({"q": "x" * 500})
    with pytest.raises(ValidationError):
        RecommendedSearchParamsIn.model_validate({"q": "x" * 501})


# ── Column-density block injected into the prompt ────────────────────────────


def _prod_shaped_coverage() -> ColumnCoverage:
    """Real prod proportions, measured 2026-08-08."""
    return ColumnCoverage(
        total=56769,
        pct={
            "embedding_id": 80.1,
            "raw_cv_text": 69.0,
            "competence_category_id": 58.8,
            "ai_summary": 26.0,
            "location": 14.8,
            "years_it_experience": 1.2,
            "skills": 0.5,
            "expected_rate_hourly": 0.0,
        },
    )


def test_sparse_columns_are_flagged_and_dense_ones_are_not():
    block = _prod_shaped_coverage().as_prompt_block()
    for sparse in ("years_it_experience", "skills", "expected_rate_hourly", "location"):
        line = next(ln for ln in block.splitlines() if ln.strip().startswith(sparse))
        assert "←" in line, f"{sparse} is below 20% and must be flagged"
    for dense in ("embedding_id", "raw_cv_text", "competence_category_id"):
        line = next(ln for ln in block.splitlines() if ln.strip().startswith(dense))
        assert "←" not in line, f"{dense} is well populated and must not be flagged"


def test_block_is_ordered_densest_first():
    rows = [
        ln for ln in _prod_shaped_coverage().as_prompt_block().splitlines()
        if "%" in ln and ln.startswith("  ")
    ]
    pcts = [float(ln.split("%")[0].split()[-1]) for ln in rows]
    assert pcts == sorted(pcts, reverse=True)


def test_empty_database_renders_nothing_rather_than_zeroes():
    """On a fresh/empty DB every column reads 0% — telling the model that
    everything is unusable would be worse than saying nothing at all."""
    assert ColumnCoverage(total=0, pct={"skills": 0.0}).as_prompt_block() == ""


# ── Preflight result count ───────────────────────────────────────────────────


def test_estimated_results_defaults_to_none_not_zero():
    """`None` means "not counted"; 0 means "counted, matches nobody". Conflating
    them would make a failed count look like a dead strategy — and a dead
    strategy look like a healthy one that simply had not been counted yet."""
    from app.schemas.champion import RecommendedSearch

    rs = RecommendedSearch(id="rs-1", name="x")
    assert rs.estimated_results is None


def test_estimated_results_survives_the_json_round_trip():
    """The field lives in `jobs.champion_profile` JSONB, so it has to come back
    out — otherwise the DL review UI reads a count that vanished on reload."""
    from app.schemas.champion import ChampionProfile, RecommendedSearch

    profile = ChampionProfile(
        recommended_searches=[
            RecommendedSearch(id="rs-1", name="x", estimated_results=0),
            RecommendedSearch(id="rs-2", name="y", estimated_results=1234),
        ]
    )
    reloaded = ChampionProfile.model_validate(profile.model_dump(mode="json"))
    assert [r.estimated_results for r in reloaded.recommended_searches] == [0, 1234]
