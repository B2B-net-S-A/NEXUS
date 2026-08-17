"""v1.1 sygnałów Championa: seniority (mnożnik) + dostępność z notatek.

Osobna flaga od v1 — v1 jest już ON na prodzie, więc v1.1 musi mieć własny
pomiar i własną drogę odwrotu. Testy zamrażają: matematykę kary, tolerancję,
parsowanie dat/wypowiedzeń PL i pełną odwracalność przy flag OFF.
"""

from datetime import date
from types import SimpleNamespace

import pytest

from app.core.config import settings
from app.services.scoring_service import (
    _SCORING_CACHE_INPUTS,
    _champion_seniority_factor,
    _notes_available_date,
    _parse_champion_date,
    _score_availability,
)


def _job(**kw):
    base = dict(champion_profile=None, deadline=None)
    base.update(kw)
    return SimpleNamespace(**base)


def _cand(**kw):
    base = dict(
        availability_date=None, cv_extracted_data=None, years_it_experience=None
    )
    base.update(kw)
    return SimpleNamespace(**base)


@pytest.fixture()
def v11_on(monkeypatch):
    # historyczna nazwa fixture; po dekompozycji włącza OBIE flagi
    monkeypatch.setattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAMPION_AVAILABILITY_FALLBACK_ENABLED", True)


def test_v11_flags_are_in_scoring_cache_inputs():
    assert "CHAMPION_SENIORITY_PENALTY_ENABLED" in _SCORING_CACHE_INPUTS
    assert "CHAMPION_AVAILABILITY_FALLBACK_ENABLED" in _SCORING_CACHE_INPUTS


def test_seniority_factor_matrix(v11_on):
    job = _job(champion_profile={"seniority_min_years": 10})
    # w tolerancji (9 vs 10) → bez kary
    f, r = _champion_seniority_factor(_cand(years_it_experience=9), job)
    assert f == 1.0 and r is None
    # niedobór 3 lata → kara (3-1)*8% = 16%
    f, r = _champion_seniority_factor(_cand(years_it_experience=7), job)
    assert abs(f - 0.84) < 1e-9 and "kara 16%" in r
    # duży niedobór → cap 32%
    f, _ = _champion_seniority_factor(_cand(years_it_experience=2), job)
    assert abs(f - 0.68) < 1e-9
    # nadwyżka → neutral
    f, r = _champion_seniority_factor(_cand(years_it_experience=15), job)
    assert f == 1.0 and r is None


def test_seniority_needs_both_sides_and_flag(monkeypatch):
    job = _job(champion_profile={"seniority_min_years": 10})
    monkeypatch.setattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", True)
    assert _champion_seniority_factor(_cand(), job) == (1.0, None), "brak lat = neutral"
    assert _champion_seniority_factor(
        _cand(years_it_experience=2), _job(champion_profile={})
    ) == (1.0, None), "brak wymagania = neutral"
    for bad in (True, "10", None):
        assert _champion_seniority_factor(
            _cand(years_it_experience=2),
            _job(champion_profile={"seniority_min_years": bad}),
        ) == (1.0, None)
    monkeypatch.setattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", False)
    assert _champion_seniority_factor(_cand(years_it_experience=2), job) == (
        1.0,
        None,
    ), "flag OFF = pełna odwracalność"


def test_parse_champion_date_formats():
    assert _parse_champion_date("1.09.2026") == date(2026, 9, 1)
    assert _parse_champion_date("2026-09-01") == date(2026, 9, 1)
    assert _parse_champion_date("start: 15/10/2026 lub później") == date(2026, 10, 15)
    today = date(2026, 8, 15)
    assert _parse_champion_date("ASAP", today=today) == today
    assert _parse_champion_date("od zaraz", today=today) == today
    assert _parse_champion_date("wrzesień") is None
    assert _parse_champion_date(None) is None
    assert _parse_champion_date("31.02.2026") is None, "nieistniejąca data = None"


def test_notes_available_date_parsing():
    today = date(2026, 8, 15)
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {"availability": {"available_from": "2026-10-01"}}
        }
    )
    assert _notes_available_date(cand, today=today) == date(2026, 10, 1)

    cand2 = _cand(
        cv_extracted_data={
            "_notes_insights": {"availability": {"notice_period": "2 tygodnie"}}
        }
    )
    assert _notes_available_date(cand2, today=today) == date(2026, 8, 29)

    cand3 = _cand(
        cv_extracted_data={
            "_notes_insights": {"availability": {"raw": "1 miesiąc wypowiedzenia"}}
        }
    )
    assert _notes_available_date(cand3, today=today) == date(2026, 9, 14)

    cand4 = _cand(
        cv_extracted_data={"_notes_insights": {"availability": {"raw": "od zaraz"}}}
    )
    assert _notes_available_date(cand4, today=today) == today

    assert _notes_available_date(_cand(), today=today) is None
    broken = _cand(cv_extracted_data={"_notes_insights": {"availability": "2 tyg"}})
    assert _notes_available_date(broken, today=today) is None, "string zamiast dict"


def test_availability_layer_uses_notes_and_champion_start(v11_on):
    job = _job(champion_profile={"start_date": "1.12.2026"})
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {"availability": {"notice_period": "1 miesiąc"}}
        }
    )
    res = _score_availability(cand, job, today=date(2026, 8, 15))
    assert res.points == res.max_points, "15.08+30 dni << 1.12 → na czas"
    assert "z notatek" in res.reason and "start Championa" in res.reason


def test_availability_layer_flag_off_ignores_fallbacks(monkeypatch):
    monkeypatch.setattr(settings, "CHAMPION_AVAILABILITY_FALLBACK_ENABLED", False)
    job = _job(champion_profile={"start_date": "1.12.2026"})
    cand = _cand(
        cv_extracted_data={
            "_notes_insights": {"availability": {"notice_period": "1 miesiąc"}}
        }
    )
    res = _score_availability(cand, job)
    assert "brak daty" in res.reason, "flag OFF: fallbacki niewidzialne"


def test_column_and_deadline_still_win_over_fallbacks(v11_on):
    job = _job(champion_profile={"start_date": "1.12.2026"}, deadline=date(2026, 9, 1))
    cand = _cand(
        availability_date=date(2026, 8, 20),
        cv_extracted_data={"_notes_insights": {"availability": {"raw": "3 miesiące"}}},
    )
    res = _score_availability(cand, job)
    assert res.points == res.max_points
    assert "z notatek" not in res.reason, "kolumna wygrywa z notatkami"


def test_asap_champion_start_uses_pinned_today(v11_on):
    """ASAP w start_date Championa musi honorować wstrzyknięte today —
    trzecia runda review złapała cichy no-op replace bez asercji trafień."""

    job = _job(champion_profile={"start_date": "ASAP"})
    cand = _cand(
        cv_extracted_data={"_notes_insights": {"availability": {"raw": "od zaraz"}}}
    )
    res = _score_availability(cand, job, today=date(2030, 1, 1))
    assert res.points == res.max_points, "obie strony = pinned today → na czas"


def test_flags_are_independent(monkeypatch):
    """Dekompozycja: każda flaga steruje WYŁĄCZNIE swoim sygnałem."""

    monkeypatch.setattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", True)
    monkeypatch.setattr(settings, "CHAMPION_AVAILABILITY_FALLBACK_ENABLED", False)
    job = _job(champion_profile={"seniority_min_years": 10, "start_date": "1.12.2026"})
    cand = _cand(
        years_it_experience=2,
        cv_extracted_data={"_notes_insights": {"availability": {"raw": "od zaraz"}}},
    )
    f, _ = _champion_seniority_factor(cand, job)
    assert f < 1.0, "kara działa przy włączonej fladze kary"
    res = _score_availability(cand, job)
    assert "brak daty" in res.reason, "fallback dostępności NIE działa bez swojej flagi"

    monkeypatch.setattr(settings, "CHAMPION_SENIORITY_PENALTY_ENABLED", False)
    monkeypatch.setattr(settings, "CHAMPION_AVAILABILITY_FALLBACK_ENABLED", True)
    f2, _ = _champion_seniority_factor(cand, job)
    assert f2 == 1.0, "kara NIE działa bez swojej flagi"
    res2 = _score_availability(cand, job)
    assert res2.points == res2.max_points, "fallback działa przy swojej fladze"
