"""„Tylko zdalnie” zapisane na profilu działa jak to z notatek (D4, 14.10.2026).

Odrzucenie z powodem „Nie akceptuje trybu pracy” zapisuje na profilu 0 dni
w biurze. Do tej pory bramka „tylko zdalnie” czytała wyłącznie notatki, więc
taki profil przy rekrutacji hybrydowej bez liczby dni nie dawał żadnego
ostrzeżenia, a przy stacjonarnej osoba wisiała na liście bez słowa. Teraz:
hybryda → plakietka (jedna, nie dwie), stacjonarnie / 4+ dni → ukryty
z licznikiem — dokładnie jak „tylko zdalnie” z notatek.

Testy w trybie domyślnym bramki (krytyczne), bo to on działa na produkcji.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.dealbreaker_filters import (
    apply_dealbreakers,
    dealbreaker_inputs_for_job,
    office_fit_status,
    remote_fit_status,
    remote_only_refuses_office,
)


def _cand(**kw):
    base = dict(
        id=7,
        skills=[{"name": "Java"}],
        verified_tech=None,
        tags=None,
        cv_extracted_data=None,
        raw_cv_text=None,
        experience=None,
        expected_rate_hourly=None,
        max_onsite_days_per_week=None,
        location=None,
        city=None,
        preferences=None,
        accepts_more_office_days=None,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _profile_remote(**kw):
    return _cand(
        preferences={"remote_modes": ["remote"]}, max_onsite_days_per_week=0, **kw
    )


def _job(policy, days=None):
    return SimpleNamespace(
        rate_budget_hourly=None,
        must_skills=None,
        onsite_days_per_week=days,
        location="Warszawa",
        remote_policy=SimpleNamespace(value=policy) if policy else None,
        champion_profile=None,
        exclude_remote_only=False,
    )


# ── predykat ────────────────────────────────────────────────────────────────


def test_profile_zero_days_is_remote_only_without_notes():
    assert remote_only_refuses_office(_profile_remote())


def test_profile_days_zero_alone_is_remote_only():
    assert remote_only_refuses_office(_cand(max_onsite_days_per_week=0))


def test_profile_remote_mode_alone_is_remote_only():
    assert remote_only_refuses_office(_cand(preferences={"remote_modes": ["remote"]}))


@pytest.mark.parametrize(
    "cand",
    [
        _cand(),  # nic nie wiemy — nieznany przechodzi
        _cand(preferences={"remote_modes": ["remote", "hybrid"]}),
        _cand(max_onsite_days_per_week=2),
        _cand(preferences={"remote_modes": []}),
        _profile_remote(accepts_more_office_days=True),
    ],
)
def test_profile_that_accepts_office_or_is_empty_is_not_remote_only(cand):
    assert not remote_only_refuses_office(cand)


# ── dopasowania ─────────────────────────────────────────────────────────────


def test_hybrid_job_without_days_shows_remote_badge():
    inputs = dealbreaker_inputs_for_job(_job("hybrid"))
    cand = _profile_remote()
    assert apply_dealbreakers([cand], inputs=inputs).kept == [cand]
    assert remote_fit_status(cand, inputs) == "prefers_remote"


def test_hybrid_job_with_days_shows_one_badge_not_two():
    """„Mniej dni w biurze” obok „Tylko zdalnie” mówi to samo dwa razy."""
    inputs = dealbreaker_inputs_for_job(_job("hybrid", days=2))
    cand = _profile_remote()
    assert apply_dealbreakers([cand], inputs=inputs).kept == [cand]
    assert remote_fit_status(cand, inputs) == "prefers_remote"
    assert office_fit_status(cand, inputs) != "days_exceeded"


def test_candidate_accepting_one_day_keeps_office_badge():
    """1 dzień to nie „tylko zdalnie” — zostaje plakietka dni w biurze."""
    inputs = dealbreaker_inputs_for_job(_job("hybrid", days=2))
    cand = _cand(
        preferences={"remote_modes": ["remote", "hybrid"]}, max_onsite_days_per_week=1
    )
    assert remote_fit_status(cand, inputs) == "ok"
    assert office_fit_status(cand, inputs) == "days_exceeded"


@pytest.mark.parametrize("job", [_job("onsite"), _job("hybrid", days=4)])
def test_onsite_or_four_days_hide_profile_remote_only(job):
    inputs = dealbreaker_inputs_for_job(job)
    res = apply_dealbreakers([_profile_remote()], inputs=inputs)
    assert res.kept == [] and res.hidden_remote_only == 1
    assert res.exclusion_reasons == {7: "remote_only"}


def test_remote_job_keeps_profile_remote_only_without_badge():
    inputs = dealbreaker_inputs_for_job(_job("remote"))
    cand = _profile_remote()
    assert apply_dealbreakers([cand], inputs=inputs).kept == [cand]
    assert remote_fit_status(cand, inputs) == "not_required"
