"""Unit tests for CV parser regex fallback (Phase D3) and Claude integration."""

from __future__ import annotations

from types import SimpleNamespace

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

    monkeypatch.setattr(cvp, "_parse_with_claude", _fail)
    out = await cvp.parse_cv("Python Developer", prefer_llm=False)
    assert out["_source"] == "regex"
    assert any(s["name"].lower() == "python" for s in out["skills"])


@pytest.mark.asyncio
async def test_parse_cv_uses_gateway_result(monkeypatch):
    expected = {
        "years_it_experience": 5,
        "current_position": "Senior Python Developer",
        "skills": [{"name": "Python", "level": "senior", "years": 5}],
        "education": [],
        "languages": [],
        "_source": "anthropic:claude-haiku-4-5",
    }

    async def _mock(_text, **_kwargs):  # type: ignore[no-untyped-def]
        return expected

    monkeypatch.setattr(cvp, "_parse_with_claude", _mock)
    out = await cvp.parse_cv("irrelevant")
    assert out["years_it_experience"] == 5
    assert out["_source"] == "anthropic:claude-haiku-4-5"
    assert "_provenance" in out


@pytest.mark.asyncio
async def test_parse_cv_falls_back_for_review_when_gateway_fails(monkeypatch):
    async def _mock(_text, **_kwargs):  # type: ignore[no-untyped-def]
        return None

    monkeypatch.setattr(cvp, "_parse_with_claude", _mock)
    out = await cvp.parse_cv("Python Developer, Docker expert.")
    assert out["_source"] == "regex"
    assert out["_needs_human_review"] is True
    names = {s["name"].lower() for s in out["skills"]}
    assert "python" in names


# ── Gateway integration ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_parse_with_claude_success(monkeypatch):
    """The provider-neutral gateway result is validated and attributed."""
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

    async def gateway_call(request):  # type: ignore[no-untyped-def]
        return SimpleNamespace(
            content=cvp._schema_validator(expected_payload),
            provider="anthropic",
            model="claude-haiku-4-5",
        )

    monkeypatch.setattr(cvp.ai_gateway, "call", gateway_call)
    out = await cvp._parse_with_claude("some cv text")

    assert out is not None
    assert out["companies"] == ["Acme Corp", "Globex"]
    assert out["career_summary"].startswith("7 lat")
    assert out["years_it_experience"] == 7
    assert out["_source"] == "anthropic:claude-haiku-4-5"


@pytest.mark.asyncio
async def test_parse_with_claude_returns_none_on_exception(monkeypatch):
    """A gateway error returns None so parse_cv marks a human-review fallback."""
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", True)

    async def gateway_call(_request):  # type: ignore[no-untyped-def]
        raise cvp.AIError("provider_error", "upstream down")

    monkeypatch.setattr(cvp.ai_gateway, "call", gateway_call)
    out = await cvp._parse_with_claude("cv")

    assert out is None


@pytest.mark.asyncio
async def test_parse_with_claude_skips_when_kill_switch_off(monkeypatch):
    """The feature kill-switch prevents gateway calls."""
    monkeypatch.setattr(cvp.settings, "CV_ENRICHMENT_ENABLED", False)

    async def fail(_request):  # type: ignore[no-untyped-def]
        raise AssertionError("gateway called despite kill-switch")

    monkeypatch.setattr(cvp.ai_gateway, "call", fail)
    out = await cvp._parse_with_claude("Python Developer")
    assert out is None


def test_schema_rejects_invalid_contacts_and_years():
    with pytest.raises(ValueError):
        cvp._schema_validator({"email": "not-email", "years_it_experience": 99})


@pytest.mark.asyncio
async def test_deterministic_contacts_override_model(monkeypatch):
    async def model(_text, **_kwargs):  # type: ignore[no-untyped-def]
        return {
            "email": "wrong@example.com",
            "phone": "500 500 500",
            "skills": [{"name": "Python", "level": None, "years": None}],
            "current_position": "Developer",
            "_source": "anthropic:claude-haiku-4-5",
        }

    monkeypatch.setattr(cvp, "_parse_with_claude", model)
    text = "Jan Kowalski\njan@source.pl\n+48 600 123 456\nPython Developer"
    out = await cvp.parse_cv(text)
    assert out["email"] == "jan@source.pl"
    assert "600" in out["phone"]
    assert out["_provenance"]["email"]["source"] == "deterministic"
    assert out["_needs_human_review"] is False


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
