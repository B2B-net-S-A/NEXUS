"""Unit tests for the AI match-justification service.

Pure logic only — no DB, no network. The LLM call is monkeypatched so the
prompt-render → sanitise pipeline is exercised deterministically. DB-backed
caching / quota gating is covered by the integration suite.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import match_justification_service as mjs


# ── Fixtures / builders ──────────────────────────────────────────────────────


def make_candidate(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        raw_cv_text="Senior DevOps Engineer. 6 lat doświadczenia. AWS, Terraform.",
        ai_summary="DevOps z chmurą AWS i automatyzacją IaC.",
        skills=["AWS", "Terraform", "Kubernetes"],
        competence_category="DevOps",
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_job(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=10,
        title="Senior DevOps Engineer",
        requirements="AWS, Terraform, Kubernetes, CI/CD",
        description="Utrzymanie platformy chmurowej.",
        must_skills=["AWS", "Terraform"],
        nice_skills=["Kubernetes"],
        champion_profile={
            "project_context": {
                "about": "Migracja do chmury",
                "responsibilities": "IaC, monitoring",
                "selling_points": "Nowoczesny stack",
            },
            "basics": {
                "candidate_location_pref": "Warszawa",
                "onsite_days_per_week": 2,
            },
        },
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_breakdown(**overrides) -> dict:
    bd = {
        "total": 78,
        "semantic": {"points": 20.0, "max": 30, "reason": "dobre dopasowanie"},
        "skills": {"points": 25.0, "max": 30, "reason": "must 2/2"},
        "salary": {"points": 5.0, "max": 10, "reason": "brak danych (neutralnie)"},
        "location": {"points": 8.0, "max": 10, "reason": "Warszawa"},
        "availability": {"points": 5.0, "max": 10, "reason": "nieznana"},
        "champion_fit": {"points": 10.0, "max": 15, "reason": "brak screeningu"},
        "matching_must": ["aws", "terraform"],
        "gap_must": [],
        "matching_nice": ["kubernetes"],
        "gap_nice": [],
        "penalties": [],
    }
    bd.update(overrides)
    return bd


# ── _input_hash ──────────────────────────────────────────────────────────────


def test_input_hash_is_stable():
    c, j, bd = make_candidate(), make_job(), make_breakdown()
    assert mjs._input_hash(c, j, bd) == mjs._input_hash(c, j, bd)


def test_input_hash_changes_when_cv_changes():
    j, bd = make_job(), make_breakdown()
    h1 = mjs._input_hash(make_candidate(), j, bd)
    h2 = mjs._input_hash(make_candidate(raw_cv_text="Zupełnie inne CV"), j, bd)
    assert h1 != h2


def test_input_hash_changes_when_score_changes():
    c, j = make_candidate(), make_job()
    h1 = mjs._input_hash(c, j, make_breakdown(total=78))
    h2 = mjs._input_hash(c, j, make_breakdown(total=42))
    assert h1 != h2


def test_input_hash_changes_when_gaps_change():
    c, j = make_candidate(), make_job()
    h1 = mjs._input_hash(c, j, make_breakdown(gap_must=[]))
    h2 = mjs._input_hash(c, j, make_breakdown(gap_must=["docker"]))
    assert h1 != h2


# ── _sanitize_llm_output ─────────────────────────────────────────────────────


def test_sanitize_output_happy_path():
    out = mjs._sanitize_llm_output(
        {
            "summary": " Dobry match. ",
            "pros": ["AWS", "Terraform"],
            "watchouts": ["K8s?"],
        }
    )
    assert out == {
        "summary": "Dobry match.",
        "pros": ["AWS", "Terraform"],
        "watchouts": ["K8s?"],
    }


def test_sanitize_output_caps_bullets_count_and_length():
    out = mjs._sanitize_llm_output(
        {
            "summary": "x",
            "pros": [f"pkt {i}" for i in range(20)],
            "watchouts": ["y" * 500],
        }
    )
    assert len(out["pros"]) == mjs._MAX_BULLETS
    assert len(out["watchouts"][0]) == mjs._MAX_BULLET_CHARS


def test_sanitize_output_drops_empty_and_nonstring_bullets():
    out = mjs._sanitize_llm_output(
        {"summary": "x", "pros": ["ok", "", "  ", None], "watchouts": "not-a-list"}
    )
    assert out["pros"] == ["ok"]
    assert out["watchouts"] == []


def test_sanitize_output_rejects_empty():
    with pytest.raises(mjs.MatchJustificationLLMError):
        mjs._sanitize_llm_output({"summary": "", "pros": [], "watchouts": []})


# ── context builders ─────────────────────────────────────────────────────────


def test_skills_to_text_variants():
    assert mjs._skills_to_text([{"name": "AWS"}, {"name": "GCP"}]) == "AWS, GCP"
    assert mjs._skills_to_text(["Java", "Kotlin"]) == "Java, Kotlin"
    assert mjs._skills_to_text("Python, Django") == "Python, Django"
    assert mjs._skills_to_text(None) == "(brak)"
    assert mjs._skills_to_text([]) == "(brak)"


def test_job_requirements_text_includes_must_and_nice():
    txt = mjs._job_requirements_text(make_job())
    assert "MUST: AWS, Terraform" in txt
    assert "NICE: Kubernetes" in txt
    assert "CI/CD" in txt  # from requirements


def test_champion_context_text_extracts_sections():
    txt = mjs._champion_context_text(make_job())
    assert "Migracja do chmury" in txt
    assert "Warszawa" in txt


def test_champion_context_text_handles_missing_profile():
    assert mjs._champion_context_text(make_job(champion_profile=None)) == (
        "(brak profilu Championa)"
    )


def test_candidate_cv_text_falls_back_to_summary():
    txt = mjs._candidate_cv_text(make_candidate(raw_cv_text=None))
    assert "DevOps z chmurą" in txt


def test_candidate_cv_text_empty_placeholder():
    txt = mjs._candidate_cv_text(make_candidate(raw_cv_text=None, ai_summary=None))
    assert txt == "(brak treści CV w systemie)"


def test_format_score_breakdown_lists_layers_and_gaps():
    txt = mjs._format_score_breakdown(make_breakdown(gap_must=["docker"]))
    assert "Wynik łączny: 78/100" in txt
    assert "Umiejętności: 25.0/30" in txt
    assert "Braki MUST: docker" in txt
    assert "Spełnione MUST: aws, terraform" in txt


# ── generate_prose (LLM monkeypatched) ───────────────────────────────────────


async def test_generate_prose_renders_prompt_and_sanitizes(monkeypatch):
    captured = {}

    async def fake_call(*, prompt, system_prompt, model, max_tokens):
        captured["prompt"] = prompt
        captured["system_prompt"] = system_prompt
        return {
            "summary": "Silne dopasowanie.",
            "pros": ["6 lat DevOps", "AWS + Terraform"],
            "watchouts": ["Potwierdzić K8s"],
        }

    monkeypatch.setattr(mjs, "_call_claude_json", fake_call)

    out = await mjs.generate_prose(make_candidate(), make_job(), make_breakdown())

    assert out["summary"] == "Silne dopasowanie."
    assert out["pros"] == ["6 lat DevOps", "AWS + Terraform"]
    assert out["watchouts"] == ["Potwierdzić K8s"]
    # The breakdown stays the model's input (which areas are strong or weak)
    # next to a concrete requirement — and the prompt forbids quoting numbers.
    assert "Spełnione MUST: aws, terraform" in captured["prompt"]
    assert "Senior DevOps Engineer" in captured["prompt"]
    assert "NIE podawaj punktacji" in captured["system_prompt"]


# ── prompt contract: the prose never states a number ────────────────────────


def test_prose_template_carries_no_score_and_forbids_quoting_one():
    """The ring shows the CANONICAL fit; this prose is generated from the
    legacy breakdown. A number in the prose would contradict the ring, so the
    template has no `{score}` and both prompts say not to cite points, scores
    or percentages — while the breakdown stays available as input."""
    template = mjs.MATCH_JUSTIFICATION
    assert template.version >= 2
    assert "{score}" not in template.template
    assert "{score_breakdown}" in template.template
    assert "NIE cytuj z niego liczb" in template.template
    for phrase in ("NIE podawaj punktacji", "„72/100”", "procentów dopasowania"):
        assert phrase in template.system_prompt


def test_prompt_inputs_are_exactly_the_template_placeholders():
    import string

    placeholders = {
        name
        for _, name, _, _ in string.Formatter().parse(mjs.MATCH_JUSTIFICATION.template)
        if name
    }
    inputs = mjs._prompt_inputs(make_candidate(), make_job(), make_breakdown())
    assert set(inputs) == placeholders


def test_known_location_and_work_mode_reach_the_prompt():
    """UAT B59: profil z miastem i trybem pracy dostawał uzasadnienie, że
    lokalizacja i tryb pracy są nieznane — model ich po prostu nie dostawał."""
    candidate = make_candidate(
        city="Łódź",
        country="PL",
        preferences={"remote_modes": ["hybrid", "remote"]},
        max_onsite_days_per_week=2,
        notice_period=1,
        notice_period_unit="months",
    )
    job = make_job(location="Warszawa", remote_policy="hybrid", onsite_days_per_week=3)
    inputs = mjs._prompt_inputs(candidate, job, make_breakdown())

    assert "Łódź, PL" in inputs["candidate_work_facts"]
    assert "hybrydowo, zdalnie" in inputs["candidate_work_facts"]
    assert "maks. dni w biurze/tydz.: 2" in inputs["candidate_work_facts"]
    assert "1 mies." in inputs["candidate_work_facts"]
    assert "Warszawa" in inputs["job_work_facts"]
    assert "tryb: hybrydowo" in inputs["job_work_facts"]
    rendered = mjs.MATCH_JUSTIFICATION.template.format(**inputs)
    assert "Łódź, PL" in rendered
    assert "brak danych kandydata" in mjs.MATCH_JUSTIFICATION.system_prompt


def test_missing_facts_are_named_as_missing_on_the_right_side():
    inputs = mjs._prompt_inputs(make_candidate(), make_job(), make_breakdown())
    assert "lokalizacja: (brak w profilu)" in inputs["candidate_work_facts"]
    assert "lokalizacja: (brak w ofercie)" in inputs["job_work_facts"]


def test_bumping_the_prompt_version_regenerates_cached_prose(monkeypatch):
    """The version is part of the cache key: prose stored under v1 is not
    served for v2 — it regenerates on the next view (lazily, not in bulk)."""
    import dataclasses

    c, j, bd = make_candidate(), make_job(), make_breakdown()
    current = mjs._input_hash(c, j, bd)
    monkeypatch.setattr(
        mjs,
        "MATCH_JUSTIFICATION",
        dataclasses.replace(mjs.MATCH_JUSTIFICATION, version=1),
    )
    assert mjs._input_hash(c, j, bd) != current


async def test_generate_prose_raises_on_unusable_output(monkeypatch):
    async def fake_call(*, prompt, system_prompt, model, max_tokens):
        return {"summary": "", "pros": [], "watchouts": []}

    monkeypatch.setattr(mjs, "_call_claude_json", fake_call)

    with pytest.raises(mjs.MatchJustificationLLMError):
        await mjs.generate_prose(make_candidate(), make_job(), make_breakdown())


@pytest.mark.asyncio
async def test_json_format_retry_is_bounded_and_preserves_budget(monkeypatch):
    import json
    from unittest.mock import AsyncMock

    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    valid = {"summary": "Podsumowanie", "pros": ["Zgodne"], "watchouts": []}
    call = AsyncMock(
        side_effect=[
            SimpleNamespace(
                content=[SimpleNamespace(text='{"summary":')], stop_reason="max_tokens"
            ),
            SimpleNamespace(
                content=[SimpleNamespace(text=json.dumps(valid))],
                stop_reason="end_turn",
            ),
        ]
    )
    monkeypatch.setattr(mjs, "run_in_threadpool", call)
    result = await mjs._call_claude_json(
        prompt="synthetic", system_prompt="", model="test", max_tokens=1500
    )
    assert result == valid
    assert call.await_count == 2
    assert (
        call.call_args_list[1].kwargs["total_timeout"]
        <= call.call_args_list[0].kwargs["total_timeout"]
    )


@pytest.mark.asyncio
async def test_json_invalid_schema_stops_after_one_retry(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    call = AsyncMock(
        return_value=SimpleNamespace(
            content=[SimpleNamespace(text='{"summary": 123}')], stop_reason="end_turn"
        )
    )
    monkeypatch.setattr(mjs, "run_in_threadpool", call)
    with pytest.raises(
        mjs.MatchJustificationLLMError, match="Invalid structured response"
    ):
        await mjs._call_claude_json(
            prompt="synthetic", system_prompt="", model="test", max_tokens=1500
        )
    assert call.await_count == 2


@pytest.mark.asyncio
async def test_transport_failure_does_not_start_format_retry(monkeypatch):
    from unittest.mock import AsyncMock

    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-test-key")
    call = AsyncMock(side_effect=TimeoutError("synthetic"))
    monkeypatch.setattr(mjs, "run_in_threadpool", call)
    with pytest.raises(mjs.MatchJustificationLLMError, match="LLM request failed"):
        await mjs._call_claude_json(
            prompt="synthetic", system_prompt="", model="test", max_tokens=1500
        )
    assert call.await_count == 1
