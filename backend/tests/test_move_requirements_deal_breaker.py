"""„Odpada, gdy…” ma skutek (04.10.2026): ostrzeżenie przy ruchu za Screening.

Czyste funkcje — bez bazy.
"""

from __future__ import annotations

from dataclasses import replace

from app.services.move_requirements import (
    PairFacts,
    build_requirements,
    deal_breaker_hits,
    deal_breaker_text,
)

PROFILE = {
    "screening_questions": [
        {
            "id": "q1",
            "question": "Czy pracujesz z Kafką?",
            "ideal_answer": "tak, produkcyjnie",
            "deal_breaker": "Zna tylko teorię.",
        },
        {
            "id": "q2",
            "question": "Ile dni w biurze akceptujesz?",
            "ideal_answer": "2",
            "deal_breaker": "Tylko praca zdalna.",
        },
    ]
}
SHEET = {
    "answers": [
        {"question_id": "q1", "response": "Tak, od 3 lat.", "deal_breaker_hit": False},
        {
            "question_id": "q2",
            "response": "Wyłącznie zdalnie.",
            "deal_breaker_hit": True,
        },
    ]
}
READY = PairFacts(
    from_column="screening",
    stage_id=21,
    screening_done=True,
    candidate_rate=True,
    availability_known=True,
)


def _item(result: dict, key: str):
    return next((i for i in result["items"] if i["key"] == key), None)


def test_hits_carry_number_question_response_and_condition() -> None:
    hits = deal_breaker_hits(SHEET, PROFILE)
    assert hits == (
        {
            "number": 2,
            "question_id": "q2",
            "question": "Ile dni w biurze akceptujesz?",
            "response": "Wyłącznie zdalnie.",
            "deal_breaker": "Tylko praca zdalna.",
        },
    )
    assert deal_breaker_text(hits) == (
        "Pytanie 2: „Ile dni w biurze akceptujesz?” — odpowiedź: „Wyłącznie "
        "zdalnie.”. Odpada, gdy: „Tylko praca zdalna.”."
    )


def test_stamped_question_text_wins_over_the_current_profile() -> None:
    sheet = {
        "answers": [
            {
                "question_id": "q2",
                "question_text": "Stare pytanie o biuro",
                "response": "",
                "deal_breaker_hit": True,
            }
        ]
    }
    (hit,) = deal_breaker_hits(sheet, PROFILE)
    assert hit["question"] == "Stare pytanie o biuro"
    assert "brak zapisanej odpowiedzi" in deal_breaker_text([hit])


def test_no_hit_no_garbage() -> None:
    assert deal_breaker_hits({"answers": []}, PROFILE) == ()
    assert deal_breaker_hits(None, PROFILE) == ()
    assert deal_breaker_hits({"answers": "x"}, None) == ()


def test_move_after_screening_warns_without_blocking() -> None:
    facts = replace(READY, deal_breaker_hits=deal_breaker_hits(SHEET, PROFILE))
    result = build_requirements(facts, "verified")
    item = _item(result, "deal_breaker")
    assert item is not None
    assert item["status"] == "missing"
    assert item["blocking"] is False
    assert item["label"] == "Odpowiedź narusza deal-breaker"
    assert item["column"] == "verified"
    assert item["action"]["kind"] == "reject"
    assert item["action"]["label"] == "Odrzuć z powodem"
    assert item["action"]["stage_id"] == 21
    assert item["action"]["note"] == item["detail"]
    # Ostrzeżenie nie zmienia głównej akcji.
    assert result["primary"]["kind"] == "move"


def test_warning_appears_once_also_for_later_columns() -> None:
    facts = replace(
        READY,
        from_column="cv_qc",
        company_cv=True,
        qc_status="passed",
        client_rate=True,
        is_client_sender=True,
        deal_breaker_hits=deal_breaker_hits(SHEET, PROFILE),
    )
    result = build_requirements(facts, "cv_sent")
    assert [i["key"] for i in result["items"]].count("deal_breaker") == 1
    assert result["primary"]["kind"] == "move"


def test_screening_column_and_backward_moves_have_no_warning() -> None:
    facts = replace(
        READY, from_column="new", deal_breaker_hits=deal_breaker_hits(SHEET, PROFILE)
    )
    assert _item(build_requirements(facts, "screening"), "deal_breaker") is None
    back = replace(facts, from_column="cv_qc")
    assert _item(build_requirements(back, "verified"), "deal_breaker") is None


def test_multiple_hits_are_one_item_with_one_line_each() -> None:
    sheet = {
        "answers": [
            {"question_id": "q1", "response": "teoria", "deal_breaker_hit": True},
            {"question_id": "q2", "response": "zdalnie", "deal_breaker_hit": True},
        ]
    }
    facts = replace(READY, deal_breaker_hits=deal_breaker_hits(sheet, PROFILE))
    item = _item(build_requirements(facts, "verified"), "deal_breaker")
    assert item["detail"].count("\n") == 1
    assert item["detail"].startswith("Pytanie 1:")
