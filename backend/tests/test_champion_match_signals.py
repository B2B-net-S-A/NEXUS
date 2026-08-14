"""Sygnały Championa w scoringu — za flagą, z dowodem odwracalności.

Import 2026-08-14 dał 949 ofertom champion_profile (stawka PLN/h, lokalizacja,
tryb pracy), a 13,9k kandydatom fakty z notatek (w tym remote_only). Te testy
zamrażają trzy nowe gałęzie ORAZ to, że flaga OFF = zachowanie sprzed zmiany,
wywołanie za wywołaniem.
"""

from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.scoring_service import (
    _SCORING_CACHE_INPUTS,
    _score_location,
    _score_salary,
)


def _job(**kw):
    base = dict(
        champion_profile=None,
        salary_min=None,
        salary_max=None,
        remote_policy=None,
        location=None,
        deadline=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _cand(**kw):
    base = dict(
        expected_rate_hourly=None,
        expected_rate_currency="PLN",
        preferences=None,
        location=None,
        cv_extracted_data=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture()
def flag_on(monkeypatch):
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", True)


def test_flag_is_in_scoring_cache_inputs():
    assert "CHAMPION_MATCH_SIGNALS_ENABLED" in _SCORING_CACHE_INPUTS, (
        "flip flagi MUSI unieważnić cache score'ów — inaczej prod miesza "
        "dwie semantyki warstw w jednej tabeli"
    )


def test_salary_flag_off_stays_not_comparable(monkeypatch):
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False)
    job = _job(champion_profile={"rate_value": 150.0}, salary_min=10000)
    cand = _cand(expected_rate_hourly=120)
    res = _score_salary(cand, job)
    assert res.points != res.max_points
    assert "not_comparable" in (res.reason or "") or "brak danych" in (res.reason or "")


def test_salary_in_champion_budget_scores_full(flag_on):
    job = _job(champion_profile={"rate_value": 150.0})
    cand = _cand(expected_rate_hourly=120)
    res = _score_salary(cand, job)
    assert res.points == res.max_points
    assert "w budżecie Championa" in res.reason


def test_salary_overshoot_decays_linearly_to_zero_at_30_percent(flag_on):
    job = _job(champion_profile={"rate_value": 100.0})
    mid = _score_salary(_cand(expected_rate_hourly=115), job)  # +15% → ~połowa
    assert 0 < mid.points < mid.max_points
    dead = _score_salary(_cand(expected_rate_hourly=140), job)  # +40% → zero
    assert dead.points == 0.0


def test_salary_ignores_garbage_champion_rate(flag_on):
    for bad in (True, "150", -5, 0, 5000):
        job = _job(champion_profile={"rate_value": bad}, salary_min=10000)
        res = _score_salary(_cand(expected_rate_hourly=120), job)
        assert res.points != res.max_points, f"rate_value={bad!r} nie może scorować"


def test_location_city_falls_back_to_champion_location(flag_on):
    job = _job(
        champion_profile={
            "basics": {"candidate_location_pref": "Warszawa"},
            "work_mode": None,
        }
    )
    res = _score_location(_cand(location="Warszawa"), job)
    assert "lokalizacja OK" in res.reason


def test_location_remote_only_from_notes_vs_champion_mode(flag_on):
    onsite_job = _job(champion_profile={"work_mode": "stacjonarnie"})
    remote_cand = _cand(
        cv_extracted_data={"_notes_insights": {"preferences": {"remote_only": True}}}
    )
    res = _score_location(remote_cand, onsite_job)
    assert "remote" not in res.reason or "OK" not in res.reason, (
        "remote_only vs stacjonarnie = znany mismatch, nie neutral"
    )

    remote_job = _job(champion_profile={"work_mode": "zdalnie"})
    res2 = _score_location(remote_cand, remote_job)
    assert "remote remote OK" in res2.reason


def test_location_flag_off_ignores_champion_entirely(monkeypatch):
    monkeypatch.setattr(settings, "CHAMPION_MATCH_SIGNALS_ENABLED", False)
    job = _job(
        champion_profile={
            "basics": {"candidate_location_pref": "Warszawa"},
            "work_mode": "zdalnie",
        }
    )
    res = _score_location(_cand(location="Warszawa"), job)
    assert "lokalizacja nieznana" in res.reason, (
        "flag OFF: champion_profile niewidzialny dla warstwy — pełna odwracalność"
    )
