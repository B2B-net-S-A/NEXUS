"""Ocena prepu z transkryptu Teams (0370): cytaty, poziom, Prep 2, notatka.

Czyste funkcje — model jest tu tylko tekstem JSON. Pilnują, że model nie
zaliczy punktu bez dowodu w rozmowie, że poziom liczy kod, że Prep 2 nie
jest karany za niepowtarzanie Prepu 1 i że awaria AI nie daje „słaby”.
"""

from __future__ import annotations

import json

import pytest

from app.services.prep_review import (
    Item,
    apply_prep1_coverage,
    grade,
    note_content,
    parse_review,
)

TRANSCRIPT = (
    "Anna Nowak: Opowiedz o Kafce.\n"
    "Jan Kowalski: W banku przez dwa lata budowałem integracje na Kafce i Springu.\n"
    "Anna Nowak: Klient zwykle pyta, jak skalujesz konsumentów.\n"
    "Jan Kowalski: Zwiększam liczbę partycji i instancji w grupie konsumentów."
)
ITEMS = [
    Item(key="must:Kafka", label="Kafka", kind="must"),
    Item(key="must:Kubernetes", label="Kubernetes", kind="must"),
    Item(key="q:7", label="Jak skalujesz konsumentów?", kind="question"),
]


def _raw(**over) -> str:
    data = {
        "summary": "Kandydat dobrze opisał Kafkę.",
        "must_haves": [
            {
                "key": "must:Kafka",
                "status": "covered",
                "quote": "budowałem integracje na Kafce",
            },
            {"key": "must:Kubernetes", "status": "missing", "quote": None},
        ],
        "client_questions": [
            {"key": "q:7", "status": "covered", "quote": "Zwiększam liczbę partycji"},
        ],
        "own_projects": {"told": True, "quote": "W banku przez dwa lata"},
    }
    data.update(over)
    return "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"


def test_parse_keeps_items_with_quotes_present_in_transcript() -> None:
    parsed = parse_review(_raw(), items=ITEMS, transcript=TRANSCRIPT)
    by_key = {i["key"]: i for i in parsed["items"]}
    assert by_key["must:Kafka"]["status"] == "covered"
    assert by_key["must:Kafka"]["quote"] == "budowałem integracje na Kafce"
    assert by_key["must:Kubernetes"]["status"] == "missing"
    assert by_key["q:7"]["kind"] == "question"
    assert parsed["own_projects"] == {"told": True, "quote": "W banku przez dwa lata"}


def test_invented_quote_downgrades_to_missing_with_flag() -> None:
    raw = _raw(
        must_haves=[
            {"key": "must:Kafka", "status": "covered", "quote": "znam Kafkę od 10 lat"},
            {"key": "must:Kubernetes", "status": "partial", "quote": None},
        ]
    )
    by_key = {
        i["key"]: i
        for i in parse_review(raw, items=ITEMS, transcript=TRANSCRIPT)["items"]
    }
    assert by_key["must:Kafka"]["status"] == "missing"
    assert by_key["must:Kafka"]["unverified"] is True
    assert by_key["must:Kubernetes"]["status"] == "missing"


def test_item_the_model_ignored_is_missing_and_unknown_keys_are_dropped() -> None:
    raw = _raw(
        client_questions=[{"key": "q:999", "status": "covered", "quote": "Zwiększam"}]
    )
    parsed = parse_review(raw, items=ITEMS, transcript=TRANSCRIPT)
    assert [i["key"] for i in parsed["items"]] == [i.key for i in ITEMS]
    assert {i["key"]: i["status"] for i in parsed["items"]}["q:7"] == "missing"


def test_own_projects_without_quote_is_not_told() -> None:
    raw = _raw(own_projects={"told": True, "quote": "nie było tego zdania"})
    assert (
        parse_review(raw, items=ITEMS, transcript=TRANSCRIPT)["own_projects"]["told"]
        is False
    )


def test_garbage_output_raises_so_caller_marks_unavailable() -> None:
    with pytest.raises(ValueError):
        parse_review("brak JSON-a", items=ITEMS, transcript=TRANSCRIPT)


def _items(*statuses: str) -> list[dict]:
    return [
        {"key": f"k{i}", "label": f"L{i}", "kind": "must", "status": s}
        for i, s in enumerate(statuses)
    ]


def test_grade_good_ok_weak() -> None:
    good = grade(
        _items("covered", "covered", "covered", "covered", "partial"),
        talk_share=0.6,
        duration_seconds=30 * 60,
        own_projects_told=True,
    )
    assert good.level == "good" and good.coverage == 0.9
    assert good.remaining == ["L4"]

    ok = grade(
        _items("covered", "covered", "missing"),
        talk_share=0.6,
        duration_seconds=30 * 60,
        own_projects_told=True,
    )
    assert ok.level == "ok"

    weak_cov = grade(
        _items("covered", "missing", "missing"),
        talk_share=0.6,
        duration_seconds=30 * 60,
        own_projects_told=True,
    )
    assert weak_cov.level == "weak"


def test_dl_talking_most_of_the_time_is_weak_even_with_full_coverage() -> None:
    result = grade(
        _items("covered", "covered"),
        talk_share=0.15,
        duration_seconds=30 * 60,
        own_projects_told=True,
    )
    assert result.level == "weak"


def test_too_short_prep_is_weak() -> None:
    result = grade(
        _items("covered"),
        talk_share=0.6,
        duration_seconds=4 * 60,
        own_projects_told=True,
    )
    assert result.level == "weak"


def test_without_own_projects_it_cannot_be_good() -> None:
    result = grade(
        _items("covered"),
        talk_share=0.6,
        duration_seconds=30 * 60,
        own_projects_told=False,
    )
    assert result.level == "ok"


def test_prep2_does_not_count_items_already_covered_in_prep1() -> None:
    items = apply_prep1_coverage(_items("missing", "missing", "covered"), {"k0", "k1"})
    assert [i["status"] for i in items] == [
        "covered_in_prep1",
        "covered_in_prep1",
        "covered",
    ]
    result = grade(
        items, talk_share=0.6, duration_seconds=20 * 60, own_projects_told=True
    )
    assert result.coverage == 1.0
    assert result.level == "good"
    assert result.remaining == []


def test_note_has_facts_and_what_is_left_for_prep2_but_no_raw_transcript() -> None:
    text = note_content(
        prep_no=1,
        level="ok",
        items=[
            {"key": "a", "label": "Kafka", "kind": "must", "status": "covered"},
            {"key": "b", "label": "Kubernetes", "kind": "must", "status": "missing"},
            {
                "key": "c",
                "label": "Skalowanie?",
                "kind": "question",
                "status": "partial",
            },
        ],
        talk_share=0.58,
        duration_seconds=31 * 60,
        summary="Dobry prep.",
        remaining=["Kubernetes", "Skalowanie?"],
    )
    assert "Ocena: OK" in text
    assert "must-have 1/2" in text
    assert "pytania klienta 0/1" in text
    assert "kandydat mówił 58% czasu" in text
    assert "Na Prep 2 zostało: Kubernetes; Skalowanie?" in text
    assert "Anna Nowak:" not in text


def test_note_when_ai_is_unavailable_has_no_grade() -> None:
    text = note_content(
        prep_no=2,
        level=None,
        items=[],
        talk_share=None,
        duration_seconds=25 * 60,
        summary=None,
        remaining=[],
    )
    assert "Ocena" not in text
    assert "niedostępne" in text
