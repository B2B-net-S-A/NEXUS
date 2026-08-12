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
    # Jawnie None: MagicMock.usage byłby truthy i wpuszczał śmieci do `_usage`.
    message.usage = None
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

    # Granica mocka = `call_claude`, nie `sys.modules["anthropic"]`. Parser
    # przechodzi teraz przez współdzielonego klienta (timeout, retry, telemetria,
    # bramka kwot) i surowego SDK nie importuje — stary mock niczego by nie
    # przechwycił, a test dotykałby sieci z fałszywym kluczem.
    from app.services import claude_client

    monkeypatch.setattr(
        claude_client,
        "call_claude",
        lambda **kwargs: _fake_anthropic_response(expected_payload),
    )
    out = await cvp._parse_with_claude("some cv text")

    assert out is not None
    assert out["companies"] == ["Acme Corp", "Globex"]
    assert out["career_summary"].startswith("7 lat")
    assert out["years_it_experience"] == 7
    assert out["_source"].startswith("claude:cv_enrichment:v")


@pytest.mark.asyncio
async def test_parse_with_claude_strips_markdown_fences(monkeypatch):
    """Real-world Claude occasionally wraps JSON in ```json fences — parser must unwrap."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    payload = {"companies": ["X"], "career_summary": None}
    fenced = "```json\n" + json.dumps(payload) + "\n```"

    # Granica mocka = `call_claude`, nie `sys.modules["anthropic"]`. Parser
    # przechodzi teraz przez współdzielonego klienta (timeout, retry, telemetria,
    # bramka kwot) i surowego SDK nie importuje — stary mock niczego by nie
    # przechwycił, a test dotykałby sieci z fałszywym kluczem.
    from app.services import claude_client

    monkeypatch.setattr(
        claude_client,
        "call_claude",
        lambda **kwargs: _fake_anthropic_response(fenced),
    )
    out = await cvp._parse_with_claude("cv")

    assert out is not None
    assert out["companies"] == ["X"]


@pytest.mark.asyncio
async def test_parse_with_claude_returns_none_on_exception(monkeypatch):
    """Any exception in Claude path → None so parse_cv can fall through."""
    monkeypatch.setattr(cvp.settings, "ANTHROPIC_API_KEY", "sk-test-key")
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    # Granica mocka = `call_claude`, nie `sys.modules["anthropic"]`. Parser
    # przechodzi teraz przez współdzielonego klienta (timeout, retry, telemetria,
    # bramka kwot) i surowego SDK nie importuje — stary mock niczego by nie
    # przechwycił, a test dotykałby sieci z fałszywym kluczem.
    from app.services import claude_client

    def exploding(**kwargs):
        raise RuntimeError("upstream down")

    monkeypatch.setattr(claude_client, "call_claude", exploding)
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
        "_source": "claude:cv_enrichment:v4",
    }

    async def _claude_mock(_text):  # type: ignore[no-untyped-def]
        return claude_payload

    async def _ollama_fail(*_a, **_k):  # type: ignore[no-untyped-def]
        raise AssertionError("Ollama should not be called when Claude succeeds")

    monkeypatch.setattr(cvp, "_parse_with_claude", _claude_mock)
    monkeypatch.setattr(cvp, "_parse_with_ollama", _ollama_fail)

    out = await cvp.parse_cv("cv text")
    assert out["companies"] == ["ClaudeCorp"]
    assert out["_source"] == "claude:cv_enrichment:v4"


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
        "_source": "ollama:cv_enrichment:v4",
    }

    async def _claude_mock(_text):  # type: ignore[no-untyped-def]
        return None

    async def _ollama_mock(_text):  # type: ignore[no-untyped-def]
        return ollama_payload

    monkeypatch.setattr(cvp, "_parse_with_claude", _claude_mock)
    monkeypatch.setattr(cvp, "_parse_with_ollama", _ollama_mock)

    out = await cvp.parse_cv("cv text")
    assert out["_source"] == "ollama:cv_enrichment:v4"
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


# ── v4: contact extraction (email / phone / name / city) ────────────────────


def test_extract_email_from_text_finds_primary_email():
    cv = "Jan Kowalski\nemail: jan.kowalski@example.com\nPython Developer"
    assert cvp._extract_email_from_text(cv) == "jan.kowalski@example.com"


def test_extract_email_lowercases_the_match():
    cv = "Contact: JAN@FOO.PL"
    assert cvp._extract_email_from_text(cv) == "jan@foo.pl"


def test_extract_email_returns_none_on_empty():
    assert cvp._extract_email_from_text("") is None
    assert cvp._extract_email_from_text("no email here") is None


def test_extract_phone_parses_polish_international():
    cv = "Jan Kowalski\nTel: +48 600 123 456\nemail: j@example.com"
    out = cvp._extract_phone_from_text(cv)
    assert out is not None
    # Digit count = 11 (48 + 9), raw match contains +48 prefix.
    digits = "".join(c for c in out if c.isdigit())
    assert len(digits) == 11
    assert "600" in out


def test_extract_phone_parses_polish_local_with_dashes():
    cv = "Name\nPhone: 600-123-456\nMore text"
    out = cvp._extract_phone_from_text(cv)
    assert out is not None
    digits = "".join(c for c in out if c.isdigit())
    assert len(digits) == 9


def test_extract_phone_rejects_short_numbers():
    cv = "Postal code: 02-137"
    # Postal code has only 5 digits — must NOT be detected as phone.
    assert cvp._extract_phone_from_text(cv) is None


def test_split_name_from_header_picks_first_nonempty_line():
    cv = "Jan Kowalski\nSenior Python Developer\nj@x.com"
    first, last = cvp._split_name_from_header(cv)
    assert first == "Jan"
    assert last == "Kowalski"


def test_split_name_skips_role_heading_lines():
    cv = "CURRICULUM VITAE\nJan Kowalski\n+48 600 000 000"
    first, last = cvp._split_name_from_header(cv)
    assert first == "Jan"
    assert last == "Kowalski"


def test_split_name_handles_polish_diacritics():
    cv = "Łukasz Żółty\nSenior Developer"
    first, last = cvp._split_name_from_header(cv)
    assert first == "Łukasz"
    assert last == "Żółty"


def test_split_name_returns_none_when_no_capitalized_pair():
    cv = "lorem ipsum\ndolor sit amet"
    first, last = cvp._split_name_from_header(cv)
    assert first is None
    assert last is None


def test_apply_contact_fallbacks_fills_only_missing_slots():
    cv = "Jan Kowalski\n+48 600 123 456\njan@example.com"
    parsed: dict = {
        "first_name": "Janusz",  # LLM already set — must NOT be overridden
        "last_name": None,
        "email": None,
        "phone": None,
        "_confidence": {"first_name": 0.95},
    }
    out = cvp._apply_contact_fallbacks(parsed, cv)
    # LLM value preserved
    assert out["first_name"] == "Janusz"
    # Regex filled the gaps
    assert out["last_name"] == "Kowalski"
    assert out["email"] == "jan@example.com"
    assert out["phone"] is not None
    # Confidence scores added for regex-filled fields
    assert out["_confidence"]["first_name"] == 0.95  # LLM-provided preserved
    assert out["_confidence"].get("last_name") == 0.6
    assert out["_confidence"].get("email") == 0.9


@pytest.mark.asyncio
async def test_regex_fallback_extracts_contact_when_no_llm():
    """End-to-end: parse_cv with no LLM finds email, phone, and name."""
    cv = """Jan Kowalski
Senior Python Developer
email: jan.kowalski@example.com
tel: +48 600 123 456
Warszawa

Experience: Python, FastAPI, Docker, Kubernetes, AWS. 8 lat doświadczenia."""
    out = await cvp.parse_cv(cv, prefer_llm=False)
    assert out["_source"] == "regex"
    assert out["first_name"] == "Jan"
    assert out["last_name"] == "Kowalski"
    assert out["email"] == "jan.kowalski@example.com"
    assert out["phone"] is not None
    assert out["years_it_experience"] == 8
    # Skills still extracted by the legacy tech regex
    assert any(s["name"].lower() == "python" for s in out["skills"])
