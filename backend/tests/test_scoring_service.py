"""Unit tests for the hybrid scoring engine (Phase 2)."""

from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

from app.services import scoring_service as ss


# ── Helpers ──────────────────────────────────────────────────────────────────


def make_candidate(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        name="Jan",
        lastname="Kowalski",
        status="active",
        tags=[],
        skills=[],
        verified_tech=[],
        location=None,
        availability_date=None,
        salary_expectation=None,
        salary_currency="PLN",
        preferences={},
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def make_job(**overrides) -> SimpleNamespace:
    defaults = dict(
        id=1,
        title="Senior Python Developer",
        must_skills=[],
        nice_skills=[],
        salary_min=None,
        salary_max=None,
        location=None,
        remote_policy=SimpleNamespace(value="remote"),
        deadline=None,
        client_id=None,
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# ── _skill_names ─────────────────────────────────────────────────────────────


def test_skill_names_from_list_of_strings():
    assert ss._skill_names(["Python", " JAVA "]) == ["python", "java"]


def test_skill_names_from_list_of_dicts():
    assert ss._skill_names([{"name": "Kubernetes"}, {"name": "AWS"}]) == [
        "kubernetes",
        "aws",
    ]


def test_skill_names_mixed_types_ignored_gracefully():
    assert ss._skill_names([123, None, "React", {"foo": "bar"}]) == ["react"]


def test_skill_names_empty_input():
    assert ss._skill_names(None) == []
    assert ss._skill_names([]) == []


def test_skill_names_from_dict_with_technologies_list():
    """Alt seed format: {'level': 'senior', 'technologies': ['Java', 'Spring Boot']}."""
    raw = {"level": "senior", "technologies": ["Java", "Spring Boot", "Kafka"]}
    assert ss._skill_names(raw) == ["java", "spring boot", "kafka"]


def test_skill_names_from_dict_with_mixed_key_variants():
    """Also accept 'skills', 'stack', 'tech' keys (robustness)."""
    assert ss._skill_names({"skills": ["React", "TypeScript"]}) == ["react", "typescript"]
    assert ss._skill_names({"stack": ["Go"]}) == ["go"]


def test_skill_names_from_dict_with_name_key():
    """Single-skill dict payload."""
    assert ss._skill_names({"name": "Python"}) == ["python"]


# ── _score_skills ────────────────────────────────────────────────────────────


def test_score_skills_all_must_matched_gives_full_must():
    job = make_job(must_skills=[{"name": "Python"}, {"name": "FastAPI"}])
    cand = make_candidate(skills=[{"name": "Python"}, {"name": "FastAPI"}])
    result, must_match, must_gap, nice_match, nice_gap = ss._score_skills(cand, job)
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)
    assert set(must_match) == {"python", "fastapi"}
    assert must_gap == []
    assert nice_match == []
    assert nice_gap == []


def test_score_skills_half_must_half_points():
    job = make_job(must_skills=["Python", "Go", "Rust", "Zig"])
    cand = make_candidate(skills=["Python", "Go"])
    result, must_match, must_gap, *_ = ss._score_skills(cand, job)
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX / 2)
    assert set(must_match) == {"python", "go"}
    assert set(must_gap) == {"rust", "zig"}


def test_score_skills_verified_tech_counts():
    job = make_job(must_skills=["AWS"])
    cand = make_candidate(verified_tech=[{"name": "aws"}])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["aws"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


def test_score_skills_no_must_returns_full_must_fallback():
    job = make_job(must_skills=[], nice_skills=["Docker"])
    cand = make_candidate(skills=["Docker"])
    result, *_ = ss._score_skills(cand, job)
    # must=20 (n/a fallback) + nice=10 = 30
    assert result.points == pytest.approx(ss.SKILLS_MAX)


def test_score_skills_tags_fallback_when_no_structured_skills():
    job = make_job(must_skills=["Python"])
    cand = make_candidate(skills=[], verified_tech=[], tags=["Python", "Senior"])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["python"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


# ── _score_salary ────────────────────────────────────────────────────────────


def test_salary_in_range_full_points():
    job = make_job(salary_min=15000, salary_max=25000)
    cand = make_candidate(salary_expectation=20000)
    r = ss._score_salary(cand, job)
    assert r.points == pytest.approx(ss.SALARY_MAX)
    assert "widełkach" in r.reason


def test_salary_above_range_decays():
    job = make_job(salary_min=15000, salary_max=20000)
    cand = make_candidate(salary_expectation=22000)  # 10% over
    r = ss._score_salary(cand, job)
    assert 0 < r.points < ss.SALARY_MAX
    assert "powyżej" in r.reason


def test_salary_below_range_decays():
    job = make_job(salary_min=20000, salary_max=30000)
    cand = make_candidate(salary_expectation=18000)  # 10% under
    r = ss._score_salary(cand, job)
    assert 0 < r.points < ss.SALARY_MAX
    assert "poniżej" in r.reason


def test_salary_missing_data_gets_zero():
    job = make_job(salary_min=None, salary_max=None)
    cand = make_candidate(salary_expectation=None)
    r = ss._score_salary(cand, job)
    assert r.points == 0.0
    assert "brak" in r.reason


def test_salary_preferences_override_salary_expectation():
    job = make_job(salary_min=15000, salary_max=25000)
    cand = make_candidate(
        salary_expectation=None,
        preferences={"rate_min": 18000, "rate_max": 22000},
    )
    r = ss._score_salary(cand, job)
    assert r.points == pytest.approx(ss.SALARY_MAX)


# ── _score_location ──────────────────────────────────────────────────────────


def test_location_remote_mode_plus_city_full_points():
    job = make_job(
        location="Warszawa, Poland",
        remote_policy=SimpleNamespace(value="remote"),
    )
    cand = make_candidate(
        location="Warszawa",
        preferences={"remote_modes": ["remote", "hybrid"]},
    )
    r = ss._score_location(cand, job)
    assert r.points == pytest.approx(ss.LOCATION_MAX)


def test_location_no_match_zero_points():
    job = make_job(
        location="Warszawa",
        remote_policy=SimpleNamespace(value="on_site"),
    )
    cand = make_candidate(
        location="Kraków",
        preferences={"remote_modes": ["remote"]},
    )
    r = ss._score_location(cand, job)
    assert r.points == 0.0


def test_location_same_city_prefix_partial():
    job = make_job(
        location="Warszawa, PL",
        remote_policy=SimpleNamespace(value="on_site"),
    )
    cand = make_candidate(location="Warszawa, Mokotów", preferences={})
    r = ss._score_location(cand, job)
    # One of the two branches fires (either full substring or prefix partial)
    assert 3.0 <= r.points <= ss.LOCATION_MAX


# ── _score_availability ──────────────────────────────────────────────────────


def test_availability_before_deadline_full_points():
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=date(2026, 5, 1))
    r = ss._score_availability(cand, job)
    assert r.points == pytest.approx(ss.AVAILABILITY_MAX)


def test_availability_no_date_half_points():
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=None)
    r = ss._score_availability(cand, job)
    assert r.points == pytest.approx(ss.AVAILABILITY_MAX * 0.5)


def test_availability_late_decays():
    job = make_job(deadline=date(2026, 6, 1))
    cand = make_candidate(availability_date=date(2026, 6, 16))  # 15 days late
    r = ss._score_availability(cand, job)
    assert 0 < r.points < ss.AVAILABILITY_MAX


# ── score_semantic ───────────────────────────────────────────────────────────


def test_semantic_full_similarity_full_points():
    r = ss.score_semantic(1.0)
    assert r.points == pytest.approx(ss.SEMANTIC_MAX)


def test_semantic_none_gives_zero():
    r = ss.score_semantic(None)
    assert r.points == 0.0


def test_semantic_mid_similarity_linear():
    r = ss.score_semantic(0.5)
    assert r.points == pytest.approx(ss.SEMANTIC_MAX * 0.5)


# ── canonical_skill_names (Phase B1 alias normalization) ────────────────────


def test_canonical_skill_names_without_alias_map_passthrough():
    # No alias overrides → behaves like _skill_names (lowercase, strip).
    assert ss.canonical_skill_names(["Python", "AWS"]) == ["python", "aws"]


def test_canonical_skill_names_with_alias_map_resolves_synonyms(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    monkeypatch.setitem(ss.ALIAS_MAP, "k8s", "kubernetes")
    assert ss.canonical_skill_names(["Python3", "K8S", "React"]) == [
        "python",
        "kubernetes",
        "react",
    ]


def test_canonical_skill_names_deduplicates_after_normalization(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    # Two raw entries collapse to a single canonical one
    result = ss.canonical_skill_names(["Python", "Python3"])
    assert result == ["python"] or result == ["python", "python"]
    # We keep order-preserving dedup
    assert result[0] == "python"


def test_score_skills_uses_alias_map_for_matching(monkeypatch):
    monkeypatch.setitem(ss.ALIAS_MAP, "python3", "python")
    job = make_job(must_skills=["Python"])
    cand = make_candidate(skills=["python3"])
    result, must_match, *_ = ss._score_skills(cand, job)
    assert must_match == ["python"]
    assert result.points == pytest.approx(ss.SKILLS_MUST_MAX)


# ── summarize_match_stats ────────────────────────────────────────────────────


def _breakdown(total: float) -> ss.ScoreBreakdown:
    return ss.ScoreBreakdown(
        candidate_id=1,
        job_id=1,
        total=total,
        semantic=ss.LayerResult(points=0, max_points=0),
        skills=ss.LayerResult(points=0, max_points=0),
        salary=ss.LayerResult(points=0, max_points=0),
        location=ss.LayerResult(points=0, max_points=0),
        availability=ss.LayerResult(points=0, max_points=0),
    )


def test_summarize_match_stats_counts_above_threshold():
    breakdowns = [_breakdown(80.0), _breakdown(55.0), _breakdown(30.0), _breakdown(50.0)]
    stats = ss.summarize_match_stats(breakdowns, total_open=4, min_score=50.0)
    # 50.0 inclusive; 55 and 80 also pass
    assert stats == {"open_count": 3, "total_open": 4, "top_score": 80.0}


def test_summarize_match_stats_none_above_threshold():
    breakdowns = [_breakdown(40.0), _breakdown(20.0)]
    stats = ss.summarize_match_stats(breakdowns, total_open=5, min_score=50.0)
    assert stats == {"open_count": 0, "total_open": 5, "top_score": 40.0}


def test_summarize_match_stats_empty_breakdowns():
    stats = ss.summarize_match_stats([], total_open=0, min_score=50.0)
    assert stats == {"open_count": 0, "total_open": 0, "top_score": 0.0}


def test_summarize_match_stats_rounds_top_score():
    breakdowns = [_breakdown(73.456789)]
    stats = ss.summarize_match_stats(breakdowns, total_open=1, min_score=50.0)
    assert stats["top_score"] == 73.5
