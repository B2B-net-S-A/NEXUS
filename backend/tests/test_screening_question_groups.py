"""Pytania kilku rekrutacji w jednej rozmowie (14.10.2026, D3) — bez bazy."""

from __future__ import annotations

import pytest

from app.services import scoring_service as scoring
from app.services.screening_question_groups import group_questions, same_question


@pytest.fixture(autouse=True)
def _aliases():
    previous = dict(scoring.ALIAS_MAP)
    scoring.set_alias_map(
        {"java": "java", "python": "python", "rxjs": "rxjs", "kafka": "kafka"}
    )
    yield
    scoring.set_alias_map(previous)


def _ids(groups):
    return [[(m.job_id, m.question_id) for m in group] for group in groups]


def test_same_text_after_folding_is_one_question() -> None:
    assert same_question("Od kiedy możesz zacząć?", "od kiedy mozesz zaczac")


def test_similar_wording_with_the_same_technology_is_one_question() -> None:
    assert same_question(
        "Jak używałeś RxJS w produkcji w ostatnim projekcie?",
        "Jak używałeś RxJS w produkcji w poprzednim projekcie?",
    )


def test_different_technology_is_a_different_question() -> None:
    assert not same_question(
        "Ile lat doświadczenia komercyjnego z Java?",
        "Ile lat doświadczenia komercyjnego z Python?",
    )


def test_rate_and_availability_questions_join_only_by_identical_text() -> None:
    # Pytania „własnej warstwy” — reguła słów byłaby dla nich zbyt luźna.
    assert not same_question(
        "Jaka jest Twoja oczekiwana stawka godzinowa na B2B?",
        "Jaka jest Twoja oczekiwana stawka dzienna na B2B?",
    )
    assert same_question("Jaka stawka?", "Jaka stawka?")


def test_groups_keep_each_job_id_and_at_most_one_question_per_job() -> None:
    groups = group_questions(
        {
            10: {
                "q1": "Jak używałeś RxJS w produkcji?",
                "q2": "Od kiedy możesz zacząć?",
                "q3": "Czy 2 dni w biurze są OK?",
            },
            20: {
                "q1": "Od kiedy możesz zacząć?",
                "q2": "Jak używałeś RxJS w produkcji?",
                "q3": "Od kiedy możesz zacząć?",
            },
        },
        [10, 20],
    )
    assert _ids(groups) == [
        [(10, "q1"), (20, "q2")],
        [(10, "q2"), (20, "q1")],
        [(10, "q3")],
        # Drugie takie samo pytanie w B nie wchodzi do grupy, w której B już jest.
        [(20, "q3")],
    ]


def test_order_follows_jobs_then_questions_and_empty_jobs_are_fine() -> None:
    groups = group_questions(
        {10: {}, 20: {"q1": "Pytanie o Kafkę na produkcji"}}, [10, 20]
    )
    assert _ids(groups) == [[(20, "q1")]]
