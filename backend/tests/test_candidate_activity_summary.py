"""Unit tests for the AI candidate-activity-summary service.

Pure logic only — no DB, no network. The LLM call is monkeypatched so the
section-render → prompt → sanitise pipeline is exercised deterministically.
DB-backed caching / quota gating is covered by the integration suite.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import candidate_activity_summary_service as cas


# ── Fixtures / builders ──────────────────────────────────────────────────────


def make_candidate(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        status=SimpleNamespace(value="active"),
        competence_category="software_development",
        skills=["Java", "Spring", "Kafka"],
        expected_rate_hourly=160,
        expected_rate_currency="PLN",
        salary_expectation=None,
        salary_currency="PLN",
        availability_status=SimpleNamespace(value="open_to_offers"),
        availability_date=date(2026, 8, 1),
        notice_period=1,
        notice_period_unit="months",
        preferences={"work_mode": "hybrid", "excluded_clients": ["Nordea"]},
        engagement_notes="Dobrze wspomina współpracę z Nordea.",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_sections(**overrides) -> dict[str, str]:
    sections = {
        "profile": "Oczekiwana stawka (profil): 160 PLN/h",
        "submissions": "- Senior Java Developer — klient: Nordea: ostatni etap "
        "„Rozmowa u klienta” (2026-06-15)",
        "feedback": "- Senior Java Developer (od klienta): decyzja: dalej w procesie",
        "screening": "(brak danych)",
        "notes": "- [2026-06-01] Kandydat preferuje hybrydę.",
        "contracts": "(brak danych)",
        "rates": "- 160 PLN (b2b) od 2026-06-01 u klienta Nordea",
        "calls": "(brak danych)",
    }
    sections.update(overrides)
    return sections


# ── _input_hash ──────────────────────────────────────────────────────────────


def test_input_hash_is_stable():
    s = make_sections()
    assert cas._input_hash(s) == cas._input_hash(s)


def test_input_hash_changes_when_history_changes():
    h1 = cas._input_hash(make_sections())
    h2 = cas._input_hash(make_sections(notes="- [2026-07-01] Nowa notatka."))
    assert h1 != h2


# ── render helpers ───────────────────────────────────────────────────────────


def test_fmt_rate_variants():
    assert cas._fmt_rate(Decimal("160.00"), "PLN", "hourly") == "160 PLN/h"
    assert cas._fmt_rate(170, None, "monthly") == "170 PLN/mies."
    assert cas._fmt_rate(None, "PLN") == ""


def test_skills_to_text_variants():
    assert cas._skills_to_text([{"name": "AWS"}, "GCP"]) == "AWS, GCP"
    assert cas._skills_to_text(None) == ""
    assert cas._skills_to_text([]) == ""


def test_truncate_appends_ellipsis():
    assert cas._truncate("x" * 20, 10).endswith(" […]")
    assert cas._truncate("krótko", 10) == "krótko"


def test_profile_section_includes_rates_availability_and_preferences():
    txt = cas._profile_section(make_candidate())
    assert "160 PLN/h" in txt
    assert "Dostępny od: 2026-08-01" in txt
    assert "Okres wypowiedzenia: 1 months" in txt
    assert "Nordea" in txt  # preferences JSON + engagement notes
    assert "Dobrze wspomina współpracę" in txt


def test_profile_section_omits_missing_fields():
    txt = cas._profile_section(
        make_candidate(
            expected_rate_hourly=None,
            availability_date=None,
            notice_period=None,
            preferences=None,
            engagement_notes=None,
            skills=None,
            competence_category=None,
            availability_status=SimpleNamespace(value="unknown"),
        )
    )
    assert "stawka" not in txt.lower()
    assert "Dostępny od" not in txt
    assert "brak danych o" not in txt.lower()


# ── _sanitize_llm_output ─────────────────────────────────────────────────────


def test_sanitize_output_strips_and_caps():
    out = cas._sanitize_llm_output("  Notatka o kandydacie.  ")
    assert out == "Notatka o kandydacie."
    long = cas._sanitize_llm_output("x" * (cas._MAX_SUMMARY_CHARS + 500))
    assert len(long) == cas._MAX_SUMMARY_CHARS


def test_sanitize_output_strips_code_fences():
    assert cas._sanitize_llm_output("```\nNotatka.\n```") == "Notatka."


def test_sanitize_output_strips_language_tagged_fences():
    assert cas._sanitize_llm_output("```text\nNotatka.\n```") == "Notatka."
    assert cas._sanitize_llm_output("```markdown\nNotatka.") == "Notatka."


def test_sanitize_output_rejects_empty():
    with pytest.raises(cas.CandidateActivitySummaryLLMError):
        cas._sanitize_llm_output("   ")


# ── generate_summary (LLM monkeypatched) ─────────────────────────────────────


async def test_generate_summary_renders_prompt_and_sanitizes(monkeypatch):
    captured = {}

    async def fake_call(*, prompt, system_prompt, model, max_tokens):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return " Kandydat był ostatnio wysyłany do Nordea. "

    monkeypatch.setattr(cas, "_call_claude_text", fake_call)

    out = await cas.generate_summary(make_sections())

    assert out == "Kandydat był ostatnio wysyłany do Nordea."
    # Concrete history facts made it into the rendered prompt.
    assert "Senior Java Developer" in captured["prompt"]
    assert "160 PLN/h" in captured["prompt"]
    assert "HISTORIA WYSYŁEK" in captured["prompt"]
    assert "NIGDY nie wymyślaj" in captured["system_prompt"]


async def test_generate_summary_raises_on_empty_output(monkeypatch):
    async def fake_call(*, prompt, system_prompt, model, max_tokens):
        return ""

    monkeypatch.setattr(cas, "_call_claude_text", fake_call)

    with pytest.raises(cas.CandidateActivitySummaryLLMError):
        await cas.generate_summary(make_sections())
