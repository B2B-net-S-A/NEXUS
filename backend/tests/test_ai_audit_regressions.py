"""Synthetic reproductions of the September AI audit: no external calls."""

from decimal import Decimal
from types import SimpleNamespace
from copy import deepcopy

import pytest

from tests.test_notes_insights_extractor import _cand, _apply
from tests.test_candidate_profile_rate_contract import _FakeProfileRateSession
from tests.test_match_justification import make_candidate, make_job, make_breakdown
from app.models.candidate import Candidate
from app.services import scoring_service as scoring, candidate_profile_facts as facts
from app.services.match_justification_service import _input_hash
from app.services.ai_metering import response_event


def rate(amount, currency="PLN"):
    return {"expected_rate": {"value": amount, "currency": currency, "period": "h"}}


def test_notes_addition_keeps_cv_skills_in_score_chips_and_hard_gate():
    from app.api.matching import _build_match_info
    from tests.test_matching_skill_sources import _candidate
    from app.services.dealbreaker_filters import missing_must_skills

    cand = _candidate(
        cv_extracted_data={"traffit_technologie": "Python, Django, PostgreSQL"}
    )
    # Fields required by notes writer.
    for name, value in vars(_cand()).items():
        if not hasattr(cand, name):
            setattr(cand, name, value)
    _apply(
        cand, {"skills_evidenced": [{"name": "Kubernetes", "evidence": "screening"}]}
    )
    assert scoring.candidate_skill_names(cand) == {
        "python",
        "django",
        "postgresql",
        "kubernetes",
    }
    assert _build_match_info(cand, ["python", "django"])["gaps"] == []
    assert missing_must_skills(cand, ["python", "django"]) == []


def test_manual_skill_override_including_empty_is_authoritative():
    for skills in ([], ["Go"]):
        cand = _cand(
            skills=skills,
            cv_extracted_data={
                "_manual_override_skills": True,
                "traffit_technologie": "Python",
            },
        )
        _apply(cand, {"skills_evidenced": [{"name": "Kubernetes"}]})
        assert scoring.candidate_skill_names(cand) == set(s.lower() for s in skills)


@pytest.mark.parametrize("manual", [Decimal("150"), Decimal("100"), None])
async def test_manual_rate_same_value_change_or_clear_blocks_ai(monkeypatch, manual):
    from unittest.mock import AsyncMock

    monkeypatch.setattr(
        "app.services.match_score_cache.mark_stale_for_candidate", AsyncMock()
    )
    cand = Candidate(id=7, profile_rate_version=0)
    _apply(cand, rate(100))
    assert cand.profile_rate_version == 1
    await facts.update_candidate_profile_rate(
        _FakeProfileRateSession(cand),
        candidate_id=7,
        amount=manual,
        expected_version=1,
        actor_id=1,
    )
    _apply(cand, rate(120))
    assert cand.expected_rate_hourly == manual
    assert cand.profile_rate_version == 2


def test_ai_rate_cas_compares_version_amount_and_currency():
    for field, value in (
        ("profile_rate_version", 8),
        ("expected_rate_hourly", Decimal("160")),
        ("expected_rate_currency", "EUR"),
    ):
        cand = _cand()
        _apply(cand, rate(100))
        setattr(cand, field, value)
        before = (
            cand.expected_rate_hourly,
            cand.expected_rate_currency,
            cand.profile_rate_version,
        )
        _apply(cand, rate(120))
        assert (
            cand.expected_rate_hourly,
            cand.expected_rate_currency,
            cand.profile_rate_version,
        ) == before


def test_currency_pair_is_never_relabelled_and_raw_foreign_rate_survives():
    cand = _cand()
    _apply(cand, rate(40, "EUR"))
    assert cand.expected_rate_hourly is None
    assert (
        cand.cv_extracted_data["_notes_insights"]["expected_rate"]["currency"] == "EUR"
    )
    _apply(cand, rate(170))
    assert (cand.expected_rate_hourly, cand.expected_rate_currency) == (
        Decimal("170"),
        "PLN",
    )
    version = cand.profile_rate_version
    _apply(cand, rate(170, "EUR"))
    assert (
        cand.expected_rate_hourly,
        cand.expected_rate_currency,
        cand.profile_rate_version,
    ) == (Decimal("170"), "PLN", version)


@pytest.mark.parametrize(
    "text,must,nice,excluded,uncertain",
    [
        (
            "Wymagane Python. Mile widziane Kubernetes. Nie wymagamy Java.",
            ["python"],
            ["kubernetes"],
            ["java"],
            [],
        ),
        (
            "Required: Python; optional Kubernetes; Java is not required.",
            ["python"],
            ["kubernetes"],
            ["java"],
            [],
        ),
        (
            "Wymagania:\n- Python\nMile widziane:\n- Kubernetes\nNiewymagane: Java",
            ["python"],
            ["kubernetes"],
            ["java"],
            [],
        ),
        ("Projekt używa Python i Kubernetes", [], [], [], ["kubernetes", "python"]),
        ("Wymagane Python. Nie wymagamy Python.", [], [], [], ["python"]),
    ],
)
def test_modality_preview_and_scoring_share_interpretation(
    text, must, nice, excluded, uncertain
):
    scoring.set_alias_map({s: s for s in ("python", "kubernetes", "java")})
    job = make_job(
        title="",
        requirements=text,
        description=None,
        must_skills=None,
        nice_skills=None,
        champion_profile=None,
    )
    assert scoring.job_skill_requirements(job) == dict(
        must=must, nice=nice, excluded=excluded, uncertain=uncertain
    )
    layer = scoring._score_skills(make_candidate(skills=["python", "kubernetes"]), job)
    assert layer[2] == []  # neither optional nor negated is a must gap
    assert layer[3] == nice


def test_champion_nice_is_scored_and_reviewed_empty_does_not_restore_it():
    job = make_job(
        must_skills=None,
        nice_skills=None,
        champion_profile={"stack": {"must": ["Python"], "nice": ["Kubernetes"]}},
    )
    assert scoring._score_skills(make_candidate(skills=["python", "kubernetes"]), job)[
        3
    ] == ["kubernetes"]
    job.requirements_reviewed = True
    assert scoring.job_skill_requirements(job)["must"] == []
    assert scoring.job_explicit_must_skills(job) == []


@pytest.mark.parametrize(
    "field,value",
    [
        ("salary", {"points": 10, "max": 10, "reason": "w budżecie"}),
        ("matching_nice", ["aws"]),
        ("penalties", ["brak dostępności"]),
    ],
)
def test_same_total_changed_prompt_invalidates_justification(field, value):
    c, j, bd = make_candidate(), make_job(), make_breakdown()
    changed = deepcopy(bd)
    changed[field] = value
    assert changed["total"] == bd["total"]
    assert _input_hash(c, j, changed) != _input_hash(c, j, bd)


def test_provider_metering_prices_cache_and_actual_fallback_model():
    message = SimpleNamespace(
        id="msg123",
        model="claude-opus-4-8",
        stop_reason="max_tokens",
        usage=SimpleNamespace(
            input_tokens=100,
            output_tokens=20,
            cache_read_input_tokens=1000,
            cache_creation_input_tokens=200,
            cache_creation=SimpleNamespace(ephemeral_1h_input_tokens=50),
        ),
    )
    event = response_event("op", message, model="claude-sonnet-5", latency_ms=12)
    assert event["model"] == "claude-opus-4-8" and event["outcome"] == "truncated"
    assert event["estimated_cost_usd"] == Decimal("0.00293750")
    assert event["cache_read_tokens"] == 1000
    assert (
        response_event("op2", message, model="x", latency_ms=1)["event_key"]
        == event["event_key"]
    )
    assert (
        response_event("op", SimpleNamespace(), model="unknown", latency_ms=1)[
            "estimated_cost_usd"
        ]
        is None
    )


def test_champion_nice_is_consistent_in_chips_and_notes_warnings():
    from app.api.matching import _parse_nice_skills
    from app.services.match_justification_service import (
        notes_gap_warnings_from_extracted,
    )

    job = make_job(
        must_skills=None,
        nice_skills=None,
        champion_profile={"stack": {"must": ["Python"], "nice": ["Kubernetes"]}},
    )
    assert _parse_nice_skills(job) == ["kubernetes"]
    assert notes_gap_warnings_from_extracted(
        {
            "_notes_insights": {
                "skills_gaps_observed": [
                    {"name": "Kubernetes", "evidence": "do sprawdzenia"}
                ]
            }
        },
        job,
    ) == [{"skill": "Kubernetes", "evidence": "do sprawdzenia"}]


@pytest.mark.parametrize(
    "prose",
    ["Mile widziane Kubernetes.", "Nie wymagamy Java.", "Projekt używa Python."],
)
def test_match_chips_do_not_restore_non_required_prose(prose):
    from app.api.matching import _required_skills_with_source

    scoring.set_alias_map({s: s for s in ("python", "java", "kubernetes")})
    job = make_job(
        title="",
        requirements=prose,
        description=None,
        champion_profile=None,
        must_skills=None,
        nice_skills=None,
    )
    assert _required_skills_with_source(job) == ([], "requirements_text")
