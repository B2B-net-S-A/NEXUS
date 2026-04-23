"""Unit tests for LinkedIn URL extraction in `app.services.cv_parser`.

Pure functions — no LLM call required. Verifies that the regex fallback
catches URLs the LLM might miss, and that the `_with_linkedin_fallback`
wrapper only backfills when the LLM's `linkedin_url` is absent.
"""

from __future__ import annotations

from app.services.cv_parser import (
    _extract_linkedin_from_text,
    _regex_fallback,
    _with_linkedin_fallback,
)


def test_extract_linkedin_canonical() -> None:
    cv = "Name: Jane Doe\nhttps://linkedin.com/in/jane-doe\nEmail: jane@x.pl"
    assert (
        _extract_linkedin_from_text(cv)
        == "https://linkedin.com/in/jane-doe"
    )


def test_extract_linkedin_with_www_and_trailing_slash() -> None:
    cv = "Check my profile: https://www.linkedin.com/in/john-smith/"
    assert (
        _extract_linkedin_from_text(cv)
        == "https://www.linkedin.com/in/john-smith/"
    )


def test_extract_linkedin_with_regional_prefix() -> None:
    cv = "pl.linkedin.com/in/jan-kowalski/ and other stuff"
    assert (
        _extract_linkedin_from_text(cv)
        == "pl.linkedin.com/in/jan-kowalski/"
    )


def test_extract_linkedin_case_insensitive() -> None:
    cv = "LinkedIn.com/in/Upper-Case"
    assert _extract_linkedin_from_text(cv) == "LinkedIn.com/in/Upper-Case"


def test_extract_linkedin_returns_none_when_absent() -> None:
    cv = "Jane Doe\nSenior Python Developer\nNo social links here."
    assert _extract_linkedin_from_text(cv) is None


def test_extract_linkedin_ignores_empty_text() -> None:
    assert _extract_linkedin_from_text("") is None


def test_regex_fallback_includes_linkedin_url() -> None:
    cv = "Python, 5 lat doświadczenia\nlinkedin.com/in/abc_123"
    fallback = _regex_fallback(cv)
    assert fallback["linkedin_url"] == "linkedin.com/in/abc_123"
    # Other fields from the legacy schema should still be present.
    assert "skills" in fallback
    assert fallback["_source"] == "regex"


def test_with_linkedin_fallback_backfills_when_llm_missed() -> None:
    llm_result = {
        "_source": "claude:cv_enrichment:v3",
        "skills": [],
        "linkedin_url": None,
    }
    cv = "Profile: linkedin.com/in/backfilled-slug"
    out = _with_linkedin_fallback(llm_result, cv)
    assert out["linkedin_url"] == "linkedin.com/in/backfilled-slug"
    # Original dict is not mutated (shallow copy).
    assert llm_result["linkedin_url"] is None


def test_with_linkedin_fallback_keeps_llm_value_when_present() -> None:
    llm_result = {
        "_source": "claude",
        "skills": [],
        "linkedin_url": "linkedin.com/in/llm-provided",
    }
    cv = "linkedin.com/in/different-regex-hit"
    out = _with_linkedin_fallback(llm_result, cv)
    # LLM wins — never clobbered by regex.
    assert out["linkedin_url"] == "linkedin.com/in/llm-provided"


def test_with_linkedin_fallback_noop_when_cv_has_no_url() -> None:
    llm_result = {"_source": "claude", "linkedin_url": None}
    cv = "Fully offline resume, no socials."
    out = _with_linkedin_fallback(llm_result, cv)
    assert out["linkedin_url"] is None
