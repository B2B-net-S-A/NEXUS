"""Termin i liczba osób z historii klienta na /jobs/new (wariant 1, 23.11.2026)."""

import pytest

from app.services.job_intake_client_defaults import defaults_from_history


def test_client_who_never_gives_a_deadline_gets_client_did_not_say() -> None:
    # Nordea na kopii z 23.11: 47 z 47 rekrutacji bez terminu.
    history = [(True, 1)] * 39 + [(True, 2)] * 8

    result = defaults_from_history(history)

    assert result == {
        "jobs": 47,
        "deadline_not_provided": 47,
        "suggest_deadline_not_provided": True,
        "headcount": 1,
        "headcount_jobs": 39,
        "suggest_headcount": True,
    }


def test_too_few_jobs_suggest_nothing() -> None:
    result = defaults_from_history([(True, 1)] * 4)

    assert result["suggest_deadline_not_provided"] is False
    assert result["suggest_headcount"] is False


@pytest.mark.parametrize("with_deadline", [2, 5])
def test_client_who_sometimes_gives_a_deadline_is_not_guessed(
    with_deadline: int,
) -> None:
    # 8 z 10 to próg; 2 z 10 z terminem to jeszcze podpowiedź, 5 z 10 już nie.
    history = [(False, 1)] * with_deadline + [(True, 1)] * (10 - with_deadline)

    result = defaults_from_history(history)

    assert result["suggest_deadline_not_provided"] is (with_deadline <= 2)


def test_headcount_without_a_clear_majority_is_not_suggested() -> None:
    history = [(True, 1)] * 6 + [(True, 2)] * 4

    result = defaults_from_history(history)

    assert result["headcount"] == 1
    assert result["suggest_headcount"] is False


def test_empty_history_is_not_an_error() -> None:
    assert defaults_from_history([]) == {
        "jobs": 0,
        "deadline_not_provided": 0,
        "suggest_deadline_not_provided": False,
        "headcount": None,
        "headcount_jobs": 0,
        "suggest_headcount": False,
    }
