"""Tests for taxonomy-first job criteria suggestions."""

from __future__ import annotations

from types import SimpleNamespace

from app.api.recommendations import (
    _fallback_criteria_from_text,
    _generate_criteria,
)
from app.api import recommendations
from app.models.job import Job
from app.services.scoring_service import set_alias_map


# ── Taxonomy and routed AI paths ───────────────────────────────────────────


async def test_unambiguous_taxonomy_does_not_call_ai(monkeypatch):
    set_alias_map({"java": "Java", "aws": "AWS"})

    async def fail(_request):  # type: ignore[no-untyped-def]
        raise AssertionError("AI should not run for explicit sections")

    monkeypatch.setattr(recommendations.ai_gateway, "call", fail)
    job = Job(
        title="Developer",
        requirements="Wymagania:\nJava\nMile widziane:\nAWS",
        description="",
    )
    result = await _generate_criteria(job, user_id=7)
    assert result["_source"] == "taxonomy"
    assert result["must_skills"] == [{"name": "java", "level": None}]
    assert result["nice_skills"] == [{"name": "aws", "level": None}]


async def test_ambiguous_taxonomy_uses_routed_ai(monkeypatch):
    set_alias_map({"java": "Java", "aws": "AWS"})
    captured = {}

    async def call(request):  # type: ignore[no-untyped-def]
        captured["request"] = request
        return SimpleNamespace(
            content={
                "must_skills": [{"name": "java", "level": None}],
                "nice_skills": [{"name": "aws", "level": None}],
            }
        )

    monkeypatch.setattr(recommendations.ai_gateway, "call", call)
    job = Job(
        id=3, client_id=5, title="Java AWS Developer", description="", requirements=""
    )
    result = await _generate_criteria(job, user_id=7)
    assert result["_source"] == "ai"
    assert captured["request"].feature.value == "criteria_suggestions"


# ── Heuristic fallback: tech-only, no prose, deterministic ─────────────────


def test_fallback_extracts_only_tech_tokens_no_prose():
    job = Job(
        title="Senior Java Developer",
        description="",
        requirements=(
            "- Java 17\n"
            "- English B2\n"
            "- Agile\n"
            "- Scrum\n"
            "- Docker\n"
            "- Bardzo dobra znajomość języka angielskiego\n"
            "- B2B cooperation"
        ),
    )
    result = _fallback_criteria_from_text(job)
    names = [s["name"] for s in result["must_skills"]] + [
        s["name"] for s in result["nice_skills"]
    ]
    lowered = [n.lower() for n in names]

    # real technologies are captured
    assert "java" in lowered
    assert "docker" in lowered
    # non-tech criteria and prose are NEVER persisted as skills
    assert "english b2" not in lowered
    assert "agile" not in lowered
    assert "scrum" not in lowered
    assert "b2b cooperation" not in lowered
    assert all("znajomość" not in n.lower() for n in names)
    # every persisted skill is a single recognised tech token (no long prose)
    assert all(len(n) <= 20 for n in names)


def test_fallback_is_deterministic_and_ordered():
    job = Job(
        title="Dev",
        description="Python Java Go Rust Docker Kubernetes AWS Redis Kafka",
        requirements="",
    )
    first = _fallback_criteria_from_text(job)
    second = _fallback_criteria_from_text(job)
    assert first == second  # old set-based impl was non-deterministic
    assert first["must_skills"][0]["name"] == "Python"  # first-seen order


def test_fallback_splits_must_then_nice():
    job = Job(
        title="",
        description=(
            "Python Java Go Rust Docker Kubernetes AWS Azure GCP Redis Kafka Django"
        ),
        requirements="",
    )
    result = _fallback_criteria_from_text(job)
    assert len(result["must_skills"]) == 8  # first 8 → must
    assert 1 <= len(result["nice_skills"]) <= 6  # overflow → nice
    must_names = {s["name"] for s in result["must_skills"]}
    nice_names = {s["name"] for s in result["nice_skills"]}
    assert must_names.isdisjoint(nice_names)  # no token in both lists


def test_fallback_dedupes_repeated_tokens():
    job = Job(
        title="Python dev", description="Python Python python", requirements="Python"
    )
    result = _fallback_criteria_from_text(job)
    all_names = [s["name"] for s in result["must_skills"] + result["nice_skills"]]
    assert len(all_names) == 1  # de-duplicated case-insensitively
