"""Scoring contract v2 — budget-100 fix + versioned cache (plan PR4).

Covers AI-P0-05 (custom weight profiles could reach a 110-point budget) and the
API-boundary + engine normalisation that closes it. Pure/DB-free.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.api.scoring_weights import WeightsPayload
from app.core.config import settings
from app.services import scoring_service as ss


def _full_candidate() -> SimpleNamespace:
    return SimpleNamespace(
        skills=[{"name": "Python"}],
        verified_tech=["PostgreSQL"],
        experience=[{"role": "Dev"}],
        years_it_experience=8,
        ai_summary="Backend engineer.",
        raw_cv_text="cv",
        availability_status=SimpleNamespace(value="available"),
    )


def _empty_candidate() -> SimpleNamespace:
    return SimpleNamespace(
        skills=None,
        verified_tech=None,
        experience=None,
        years_it_experience=None,
        ai_summary=None,
        raw_cv_text=None,
        availability_status=SimpleNamespace(value="unknown"),
    )


def test_fit_confidence_full_vs_empty():
    job_full = SimpleNamespace(must_skills=[{"name": "Python"}])
    job_bare = SimpleNamespace(must_skills=None)
    assert ss.compute_fit_confidence(_full_candidate(), job_full) == 1.0
    assert ss.compute_fit_confidence(_empty_candidate(), job_bare) == 0.0


def test_fit_confidence_partial_is_fraction():
    cand = SimpleNamespace(
        skills=[{"name": "Go"}],
        verified_tech=None,
        experience=[{"role": "Dev"}],
        years_it_experience=5,
        ai_summary=None,
        raw_cv_text=None,
        availability_status=SimpleNamespace(value="unknown"),
    )
    job = SimpleNamespace(must_skills=[{"name": "Go"}])
    # present: skills, experience, years, must_skills = 4 of 7 signals.
    assert ss.compute_fit_confidence(cand, job) == round(4 / 7, 3)


def test_fit_confidence_is_separate_from_score():
    # Confidence is not part of the point budget — it never touches `total`.
    bd = ss.ScoreBreakdown(
        candidate_id=1,
        job_id=2,
        total=87.0,
        semantic=ss.LayerResult(30, 35),
        skills=ss.LayerResult(25, 30),
        salary=ss.LayerResult(10, 12),
        location=ss.LayerResult(8, 8),
        availability=ss.LayerResult(4, 5),
        fit_confidence=0.43,
    )
    d = bd.as_dict()
    assert d["fit_confidence"] == 0.43
    assert d["total"] == 87.0


def _record(weights: dict) -> SimpleNamespace:
    return SimpleNamespace(id=7, name="custom", weights=weights)


LEGACY_FIVE = {
    "semantic": 40,
    "skills": 30,
    "salary": 15,
    "location": 10,
    "availability": 5,
}  # sums to 100 over five layers, no champion_fit


def test_from_record_flag_off_preserves_legacy_budget(monkeypatch):
    monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", False)
    p = ss.WeightProfile.from_record(_record(LEGACY_FIVE))
    # Legacy behaviour: champion defaults to the full 10 → budget overshoots 100.
    assert p.champion_fit == ss.CHAMPION_FIT_MAX
    budget = (
        p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    )
    assert budget == 110.0


def test_from_record_flag_on_normalises_budget_to_100(monkeypatch):
    monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", True)
    p = ss.WeightProfile.from_record(_record(LEGACY_FIVE))
    # Champion absorbs the unallocated budget (here 0) → exactly 100.
    assert p.champion_fit == 0.0
    budget = (
        p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    )
    assert budget == 100.0


def test_from_record_flag_on_with_headroom(monkeypatch):
    monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", True)
    # Five layers sum to 85 → champion takes the remaining 15.
    p = ss.WeightProfile.from_record(
        _record(
            {
                "semantic": 35,
                "skills": 25,
                "salary": 15,
                "location": 5,
                "availability": 5,
            }
        )
    )
    assert p.champion_fit == 15.0
    total = (
        p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    )
    assert total == 100.0


def test_from_record_explicit_champion_used_regardless_of_flag(monkeypatch):
    weights = {**LEGACY_FIVE, "salary": 7, "champion_fit": 8}  # 40+30+7+10+5+8 = 100
    for flag in (True, False):
        monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", flag)
        p = ss.WeightProfile.from_record(_record(weights))
        assert p.champion_fit == 8.0


def test_scoring_algorithm_version_is_known_string():
    version = ss.scoring_algorithm_version()
    base = version.split("+emb-")[0]
    assert base in {"score-v1-legacy", "score-v2-budget100"}, version
    assert "+emb-" in version, "embedding model no longer folded in (AI-P0-06)"
    # Must fit the DB column (VARCHAR(64), migration 0185) — else cache INSERTs
    # fail silently and the whole match-score cache stops persisting.
    assert len(version) <= 64, f"version {version!r} exceeds column width"


def test_calibration_knobs_are_part_of_the_cache_key(monkeypatch):
    """`config.py` promises "full rollback without a redeploy: set 1.0 / 0.0".

    That was untrue in both directions: the knobs were absent from the version
    string, so flipping them left every cached score in place and the list
    silently mixed two calibrations. It had to be patched by hand twice
    (migrations 0143, 0150).
    """
    before = ss.scoring_algorithm_version()

    monkeypatch.setattr(ss, "SEMANTIC_CALIBRATION_GAMMA", 1.0)
    assert ss.scoring_algorithm_version() != before, (
        "changing the semantic calibration does not invalidate cached scores"
    )

    monkeypatch.setattr(ss, "SEMANTIC_CALIBRATION_GAMMA", 0.6)
    monkeypatch.setattr(ss, "UNKNOWN_NEUTRAL_FRACTION", 0.0)
    assert ss.scoring_algorithm_version() != before, (
        "changing the unknown-data fraction does not invalidate cached scores"
    )


def test_embedding_text_schema_is_part_of_the_cache_key(monkeypatch):
    """`AI_TEXT_SCHEMA_V2` rewrites the embedded text, hence the similarity,
    hence the score — a cached value from the other schema is not comparable."""
    before = ss.scoring_algorithm_version()
    monkeypatch.setattr(
        settings, "AI_TEXT_SCHEMA_V2", not getattr(settings, "AI_TEXT_SCHEMA_V2", False)
    )
    assert ss.scoring_algorithm_version() != before


def test_unrelated_settings_do_not_churn_the_cache(monkeypatch):
    """The input list is explicit rather than a dump of the whole config, so a
    setting that has nothing to do with scoring cannot invalidate 100k rows on
    an ordinary deploy."""
    before = ss.scoring_algorithm_version()
    monkeypatch.setattr(settings, "QDRANT_PORT", 9999)
    assert ss.scoring_algorithm_version() == before


def test_float_noise_does_not_invalidate_the_cache(monkeypatch):
    """0.6 parsed slightly differently must not read as a new calibration."""
    monkeypatch.setattr(ss, "SEMANTIC_CALIBRATION_GAMMA", 0.6)
    a = ss.scoring_algorithm_version()
    monkeypatch.setattr(ss, "SEMANTIC_CALIBRATION_GAMMA", 0.6 + 1e-9)
    assert ss.scoring_algorithm_version() == a


def test_unknown_neutral_fraction_default_matches_config():
    """The module fell back to 0.5 while `config.py` documented 0.65, so any
    environment missing the setting quietly ran a second, unchosen calibration."""
    import inspect

    src = inspect.getsource(ss)
    assert 'getattr(settings, "SCORE_UNKNOWN_NEUTRAL_FRACTION", 0.65)' in src


def test_weights_payload_accepts_legacy_five(monkeypatch):
    # champion_fit omitted → defaults to 0; the five must still sum to 100.
    payload = WeightsPayload(
        semantic=40, skills=30, salary=15, location=10, availability=5
    )
    assert payload.champion_fit == 0


def test_weights_payload_accepts_six():
    payload = WeightsPayload(
        semantic=35, skills=30, salary=12, location=8, availability=5, champion_fit=10
    )
    assert payload.champion_fit == 10


def test_weights_payload_rejects_bad_sum():
    with pytest.raises(ValueError):
        WeightsPayload(
            semantic=40,
            skills=30,
            salary=15,
            location=10,
            availability=5,
            champion_fit=10,
        )  # sums to 110
