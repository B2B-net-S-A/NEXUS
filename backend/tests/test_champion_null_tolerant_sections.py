"""UAT M04-B01: pusty „Deal breaker" we wzorze nie może wywracać importu."""

import pytest
from pydantic import ValidationError

from app.schemas.champion import ChampionProfile


def test_parser_nulls_in_optional_text_fields_become_empty_strings():
    profile = ChampionProfile.model_validate(
        {
            "screening_questions": [
                {
                    "id": "q1",
                    "question": "Ile lat pracujesz z Pythonem?",
                    "ideal_answer": None,
                    "deal_breaker": None,
                }
            ],
            "search": {"keywords": None, "disqualifiers": None, "notes": None},
            "stack": {"must": [{"name": "Python"}], "notes": None},
            "project": {"about": None, "responsibilities": None},
            "client": {"about": None, "selling_points": None, "sectors": None},
        }
    )

    question = profile.screening_questions[0]
    assert question.deal_breaker == ""
    assert question.ideal_answer == ""
    assert profile.search.keywords == ""
    assert profile.search.disqualifiers == []
    assert profile.project.about == ""
    assert profile.client.sectors == []
    assert [item.name for item in profile.stack.must] == ["Python"]


def test_required_screening_question_text_still_fails_when_missing():
    with pytest.raises(ValidationError):
        ChampionProfile.model_validate(
            {"screening_questions": [{"id": "q1", "question": None}]}
        )


def test_null_in_optional_basics_keeps_meaning_of_unknown():
    profile = ChampionProfile.model_validate(
        {"basics": {"rate_value": None, "language": None}}
    )
    assert profile.basics.rate_value is None
    assert profile.basics.language is None
