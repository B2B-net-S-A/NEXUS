from types import SimpleNamespace

import pytest

from app.services import scoring_service as scoring
from app.services.dealbreaker_filters import (
    DealbreakerInputs,
    rate_fit_status,
    resolve_job_budget_hourly,
)
from app.services.talent_radar_search import RadarQuery, build_ephemeral_job


def candidate(currency="PLN", amount=120):
    return SimpleNamespace(expected_rate_hourly=amount, expected_rate_currency=currency)


def test_explicit_job_budget_drives_both_filter_and_score(monkeypatch):
    job = SimpleNamespace(rate_budget_hourly=150, salary_min=None, salary_max=None)
    monkeypatch.setattr(scoring, "get_champion_hourly_rate", lambda _: 90)
    budget = resolve_job_budget_hourly(job)
    assert budget == 150
    assert rate_fit_status(candidate(), DealbreakerInputs(budget_hourly=budget)) == "ok"
    result = scoring._score_salary(candidate(), job)
    assert result.points == result.max_points
    assert "150 PLN/h" in result.reason


def test_radar_manual_budget_reaches_score():
    job = build_ephemeral_job(
        RadarQuery(client_id=1, text="Python", budget_hourly_max=150)
    )
    assert job.rate_budget_hourly == 150
    result = scoring._score_salary(candidate(), job)
    assert result.points == result.max_points


@pytest.mark.parametrize("currency", [None, "", "EUR"])
def test_no_currency_assumption_in_either_layer(currency):
    job = SimpleNamespace(rate_budget_hourly=150, salary_min=None, salary_max=None)
    cand = candidate(currency=currency)
    assert rate_fit_status(cand, DealbreakerInputs(budget_hourly=150)) == "unknown"
    assert "not_comparable" in scoring._score_salary(cand, job).reason


def test_explicit_budget_retains_strict_ceiling():
    inputs = DealbreakerInputs(budget_hourly=150)
    assert rate_fit_status(candidate(amount=150), inputs) == "ok"
    assert rate_fit_status(candidate(amount=150.01), inputs) == "over_budget"
