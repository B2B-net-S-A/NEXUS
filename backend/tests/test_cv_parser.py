"""Unit tests for CV parser regex fallback (Phase D3) and Claude integration."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

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


def test_regex_fallback_has_empty_companies_and_null_summary():
    """Schema consistency with Claude/Ollama output — frontend reads these."""
    out = cvp._regex_fallback("Python Developer, 5 years.")
    assert out["companies"] == []
    assert out["career_summary"] is None


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
    # Make sure Claude is disabled for this test
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "")
    out = await cvp.parse_cv("Python Developer, Docker expert.")
    assert out["_source"] == "regex"
    names = {s["name"].lower() for s in out["skills"]}
    assert "python" in names


# ── Claude integration ──────────────────────────────────────────────────────


def _fake_anthropic_response(payload: dict | str) -> MagicMock:
    """Build a mock that mirrors the real anthropic Messages response shape."""
    text = payload if isinstance(payload, str) else json.dumps(payload)
    content_block = MagicMock()
    content_block.text = text
    message = MagicMock()
    message.content = [content_block]
    return message


@pytest.mark.asyncio
async def test_parse_with_claude_success(monkeypatch):
    """Claude returns structured JSON; parser surfaces it with claude _source."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    expected_payload = {
        "years_it_experience": 7,
        "current_position": "Senior Backend Developer",
        "skills": [{"name": "Python", "level": "senior", "years": 7}],
        "education": [],
        "languages": [{"name": "English", "level": "C1"}],
        "companies": ["Acme Corp", "Globex"],
        "career_summary": "7 lat doświadczenia w backendzie, głównie Python.",
    }

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response(
        expected_payload
    )
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = fake_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        out = await cvp._parse_with_claude("some cv text")

    assert out is not None
    assert out["companies"] == ["Acme Corp", "Globex"]
    assert out["career_summary"].startswith("7 lat")
    assert out["years_it_experience"] == 7
    assert out["_source"] == "claude:cv_enrichment:v2"


@pytest.mark.asyncio
async def test_parse_with_claude_strips_markdown_fences(monkeypatch):
    """Real-world Claude occasionally wraps JSON in ```json fences — parser must unwrap."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    payload = {"companies": ["X"], "career_summary": None}
    fenced = "```json\n" + json.dumps(payload) + "\n```"

    fake_client = MagicMock()
    fake_client.messages.create.return_value = _fake_anthropic_response(fenced)
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = fake_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        out = await cvp._parse_with_claude("cv")

    assert out is not None
    assert out["companies"] == ["X"]


@pytest.mark.asyncio
async def test_parse_with_claude_returns_none_on_exception(monkeypatch):
    """Any exception in Claude path → None so parse_cv can fall through."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    fake_client = MagicMock()
    fake_client.messages.create.side_effect = RuntimeError("upstream down")
    mock_anthropic = MagicMock()
    mock_anthropic.Anthropic.return_value = fake_client

    with patch.dict("sys.modules", {"anthropic": mock_anthropic}):
        out = await cvp._parse_with_claude("cv")

    assert out is None


@pytest.mark.asyncio
async def test_parse_with_claude_returns_none_when_no_api_key(monkeypatch):
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "")
    out = await cvp._parse_with_claude("cv")
    assert out is None


@pytest.mark.asyncio
async def test_parse_cv_prefers_claude_over_ollama(monkeypatch):
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    claude_payload = {
        "companies": ["ClaudeCorp"],
        "career_summary": "from claude",
        "skills": [],
        "education": [],
        "languages": [],
        "years_it_experience": 1,
        "current_position": None,
        "_source": "claude:cv_enrichment:v2",
    }

    async def _claude_mock(_text):  # type: ignore[no-untyped-def]
        return claude_payload

    async def _ollama_fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("Ollama should not be called when Claude succeeds")

    monkeypatch.setattr(cvp, "_parse_with_claude", _claude_mock)
    monkeypatch.setattr(cvp, "_parse_with_ollama", _ollama_fail)

    out = await cvp.parse_cv("cv text")
    assert out["companies"] == ["ClaudeCorp"]
    assert out["_source"] == "claude:cv_enrichment:v2"


@pytest.mark.asyncio
async def test_parse_cv_falls_back_to_ollama_when_claude_fails(monkeypatch):
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    ollama_payload = {
        "companies": ["OllamaCorp"],
        "career_summary": "from ollama",
        "skills": [],
        "education": [],
        "languages": [],
        "years_it_experience": 2,
        "current_position": None,
        "_source": "ollama:cv_enrichment:v2",
    }

    async def _claude_mock(_text):  # type: ignore[no-untyped-def]
        return None

    async def _ollama_mock(_text):  # type: ignore[no-untyped-def]
        return ollama_payload

    monkeypatch.setattr(cvp, "_parse_with_claude", _claude_mock)
    monkeypatch.setattr(cvp, "_parse_with_ollama", _ollama_mock)

    out = await cvp.parse_cv("cv text")
    assert out["_source"] == "ollama:cv_enrichment:v2"
    assert out["companies"] == ["OllamaCorp"]


@pytest.mark.asyncio
async def test_parse_with_claude_skips_when_kill_switch_off(monkeypatch):
    """Kill-switch lives inside _parse_with_claude — no SDK import, no API call."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", False)

    # Anthropic must NOT be imported at all when the switch is off.
    # If the gate is bypassed and something tries to `import anthropic`, we force
    # it to explode loudly by stubbing sys.modules with a sentinel.
    sentinel = MagicMock()
    sentinel.Anthropic.side_effect = AssertionError(
        "anthropic client instantiated despite CV_ENRICHMENT_ENABLED=False"
    )
    with patch.dict("sys.modules", {"anthropic": sentinel}):
        out = await cvp._parse_with_claude("Python Developer")
    assert out is None
