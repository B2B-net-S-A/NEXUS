"""Unit tests for CV parser regex fallback (Phase D3)."""

from __future__ import annotations

import pytest

from app.services import cv_parser as cvp


# ── _regex_fallback happy paths ──────────────────────────────────────────────


def test_regex_fallback_extracts_common_tech():
    cv = """
    Senior Python Developer
    Experience: Python, Django, FastAPI, PostgreSQL, Redis, Docker, AWS.
    Built REST APIs and GraphQL endpoints.
    """
    out = cvp._regex_fallback(cv)
    names = {s["name"].lower() for s in out["skills"]}
    assert "python" in names
    assert "django" in names
    assert "fastapi" in names
    assert "postgresql" in names
    assert "docker" in names
    assert "aws" in names
    assert out["_source"] == "regex"


def test_regex_fallback_caps_skills_at_20():
    cv = "Python Java JavaScript TypeScript React Angular Vue Node Go Rust " * 5
    out = cvp._regex_fallback(cv)
    assert len(out["skills"]) <= 20


def test_regex_fallback_extracts_years_polish():
    cv = "8 lat doświadczenia w IT, Senior Software Engineer."
    out = cvp._regex_fallback(cv)
    assert out["years_it_experience"] == 8


def test_regex_fallback_extracts_years_english():
    cv = "10 years experience building backend systems."
    out = cvp._regex_fallback(cv)
    assert out["years_it_experience"] == 10


def test_regex_fallback_drops_implausible_years():
    cv = "99 lat w branży"
    out = cvp._regex_fallback(cv)
    assert out["years_it_experience"] is None


def test_regex_fallback_no_years():
    cv = "Developer writing Python and Go."
    out = cvp._regex_fallback(cv)
    assert out["years_it_experience"] is None


def test_regex_fallback_detects_current_position():
    cv = """Senior Python Developer
Contact: foo@bar.com

Summary: built many things."""
    out = cvp._regex_fallback(cv)
    assert out["current_position"] is not None
    assert "Senior Python" in out["current_position"]


def test_regex_fallback_on_empty_input():
    out = cvp._regex_fallback("")
    assert out["skills"] == []
    assert out["years_it_experience"] is None
    assert out["current_position"] is None
    assert out["_source"] == "regex"


def test_regex_fallback_education_languages_are_empty():
    """The regex fallback cannot extract education/languages — by design."""
    out = cvp._regex_fallback("Any text about Python.")
    assert out["education"] == []
    assert out["languages"] == []


# ── parse_cv async wrapper ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_cv_empty_input_returns_regex_fallback():
    out = await cvp.parse_cv("")
    assert out["skills"] == []
    assert out["_source"] == "regex"


@pytest.mark.asyncio
async def test_parse_cv_skip_llm_respected(monkeypatch):
    async def _fail(*a, **k):  # type: ignore[no-untyped-def]
        raise AssertionError("should not be called when prefer_llm=False")

    monkeypatch.setattr(cvp, "_parse_with_ollama", _fail)
    out = await cvp.parse_cv("Python Developer", prefer_llm=False)
    assert out["_source"] == "regex"
    assert any(s["name"].lower() == "python" for s in out["skills"])


@pytest.mark.asyncio
async def test_parse_cv_uses_ollama_when_available(monkeypatch):
    expected = {
        "years_it_experience": 5,
        "current_position": "Senior Python Developer",
        "skills": [{"name": "Python", "level": "senior", "years": 5}],
        "education": [],
        "languages": [],
        "_source": "ollama:cv_enrichment:v1",
    }

    async def _mock(_text):  # type: ignore[no-untyped-def]
        return expected

    monkeypatch.setattr(cvp, "_parse_with_ollama", _mock)
    out = await cvp.parse_cv("irrelevant")
    assert out == expected


@pytest.mark.asyncio
async def test_parse_cv_falls_back_when_ollama_fails(monkeypatch):
    async def _mock(_text):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(cvp, "_parse_with_ollama", _mock)
    out = await cvp.parse_cv("Python Developer, Docker expert.")
    assert out["_source"] == "regex"
    names = {s["name"].lower() for s in out["skills"]}
    assert "python" in names
