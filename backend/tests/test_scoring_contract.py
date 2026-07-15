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
    budget = p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    assert budget == 110.0


def test_from_record_flag_on_normalises_budget_to_100(monkeypatch):
    monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", True)
    p = ss.WeightProfile.from_record(_record(LEGACY_FIVE))
    # Champion absorbs the unallocated budget (here 0) → exactly 100.
    assert p.champion_fit == 0.0
    budget = p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    assert budget == 100.0


def test_from_record_flag_on_with_headroom(monkeypatch):
    monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", True)
    # Five layers sum to 85 → champion takes the remaining 15.
    p = ss.WeightProfile.from_record(
        _record({"semantic": 35, "skills": 25, "salary": 15, "location": 5, "availability": 5})
    )
    assert p.champion_fit == 15.0
    total = p.semantic + p.skills + p.salary + p.location + p.availability + p.champion_fit
    assert total == 100.0


def test_from_record_explicit_champion_used_regardless_of_flag(monkeypatch):
    weights = {**LEGACY_FIVE, "salary": 7, "champion_fit": 8}  # 40+30+7+10+5+8 = 100
    for flag in (True, False):
        monkeypatch.setattr(settings, "AI_SCORING_CONTRACT_V2", flag)
        p = ss.WeightProfile.from_record(_record(weights))
        assert p.champion_fit == 8.0


def test_scoring_algorithm_version_is_known_string():
    assert ss.SCORING_ALGORITHM_VERSION in {
        "score-v1-legacy",
        "score-v2-budget100",
    }


def test_weights_payload_accepts_legacy_five(monkeypatch):
    # champion_fit omitted → defaults to 0; the five must still sum to 100.
    payload = WeightsPayload(semantic=40, skills=30, salary=15, location=10, availability=5)
    assert payload.champion_fit == 0


def test_weights_payload_accepts_six():
    payload = WeightsPayload(
        semantic=35, skills=30, salary=12, location=8, availability=5, champion_fit=10
    )
    assert payload.champion_fit == 10


def test_weights_payload_rejects_bad_sum():
    with pytest.raises(ValueError):
        WeightsPayload(
            semantic=40, skills=30, salary=15, location=10, availability=5, champion_fit=10
        )  # sums to 110
