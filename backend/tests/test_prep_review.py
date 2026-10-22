"""Ocena prepu v2 (0370 + 0505): cytaty, wynik z wag, notatka na Prep 2.

Czyste funkcje — model jest tu tylko tekstem JSON. Pilnują, że model nie
zaliczy punktu bez dowodu w rozmowie, że wynik i poziom liczy kod z ustawień,
że Prep 1 daje listę „Do powtórzenia na Prep 2”, Prep 2 porównuje się
z Prepem 1, a awaria AI nie daje „słaby”.
"""

from __future__ import annotations

import json

import pytest

from app.services import prep_review_config as cfg
from app.services.prep_review import build_prompt, prep1_followup_of, topic_items
from app.services.prep_review_scoring import (
    Item,
    comparison,
    followup_items,
    legacy_items,
    mark_covered_in_prep1,
    note_content,
    parse_review,
    score_review,
)

TRANSCRIPT = (
    "Delivery Lead: Opowiedz o Kafce. Klient to zespół płatności.\n"
    "Kandydat: W banku przez dwa lata budowałem integracje na Kafce i Springu.\n"
    "Delivery Lead: Klient zwykle pyta, jak skalujesz konsumentów.\n"
    "Kandydat: Mamy partycje, jakoś to działa.\n"
    "Delivery Lead: A Kubernetes?\n"
    "Kandydat: Nie pracowałem z tym za dużo, raczej ktoś inny wdrażał."
)
ITEMS = [
    Item("topic:0", "Klient i projekt", "topic", required=True),
    Item("topic:1", "Przebieg rozmowy u klienta", "topic", required=True),
    Item("must:Kafka", "Kafka", "must"),
    Item("must:Kubernetes", "Kubernetes", "must"),
    Item("q:7", "Jak skalujesz konsumentów?", "question"),
]


def _raw(**over) -> str:
    data = {
        "summary": "Kandydat dobrze opisał Kafkę, słabo Kubernetes.",
        "topics": [
            {
                "key": "topic:0",
                "status": "covered",
                "quote": "Klient to zespół płatności",
            },
            {"key": "topic:1", "status": "missing", "quote": None},
        ],
        "answers": [
            {
                "key": "must:Kafka",
                "grade": "strong",
                "quote": "budowałem integracje na Kafce",
                "note": None,
            },
            {
                "key": "must:Kubernetes",
                "grade": "weak",
                "quote": "Nie pracowałem z tym za dużo",
                "note": "Przygotuj jeden przykład wdrożenia.",
            },
            {
                "key": "q:7",
                "grade": "general",
                "quote": "Mamy partycje, jakoś to działa",
                "note": "Powiedz, co sam ustawiałeś.",
            },
        ],
        "went_well": ["Projekt na Kafce z konkretami"],
        "went_wrong": ["Kubernetes bez przykładu"],
        "improve": ["Omów przebieg rozmowy u klienta"],
        "own_projects": {"told": True, "quote": "W banku przez dwa lata"},
    }
    data.update(over)
    return "```json\n" + json.dumps(data, ensure_ascii=False) + "\n```"


def _config(**changes) -> cfg.PrepReviewConfig:
    data = cfg.defaults().model_dump()
    data.update(changes)
    return cfg.PrepReviewConfig.model_validate(data)


def _parsed(**over) -> dict:
    return parse_review(_raw(**over), items=ITEMS, transcript=TRANSCRIPT)


# ── Parsowanie ───────────────────────────────────────────────────────────────


def test_parse_keeps_grades_with_quotes_present_in_transcript() -> None:
    parsed = _parsed()
    answers = {a["key"]: a for a in parsed["answers"]}
    assert answers["must:Kafka"]["grade"] == "strong"
    assert answers["must:Kubernetes"]["grade"] == "weak"
    assert answers["must:Kubernetes"]["note"] == "Przygotuj jeden przykład wdrożenia."
    assert answers["q:7"]["kind"] == "question"
    topics = {t["key"]: t for t in parsed["topics"]}
    assert topics["topic:0"]["status"] == "covered"
    assert topics["topic:1"]["required"] is True
    assert parsed["went_wrong"] == ["Kubernetes bez przykładu"]
    assert parsed["own_projects"] == {"told": True, "quote": "W banku przez dwa lata"}


def test_invented_quote_downgrades_to_missing_with_flag() -> None:
    raw = _raw(
        answers=[
            {"key": "must:Kafka", "grade": "strong", "quote": "znam Kafkę od 10 lat"},
            {"key": "must:Kubernetes", "grade": "general", "quote": None},
            {"key": "q:7", "grade": "weak", "quote": "Mamy partycje"},
        ]
    )
    answers = {
        a["key"]: a
        for a in parse_review(raw, items=ITEMS, transcript=TRANSCRIPT)["answers"]
    }
    assert answers["must:Kafka"]["grade"] == "missing"
    assert answers["must:Kafka"]["unverified"] is True
    assert answers["must:Kubernetes"]["grade"] == "missing"
    assert answers["q:7"]["grade"] == "weak"


def test_point_the_model_ignored_is_missing_and_unknown_keys_are_dropped() -> None:
    raw = _raw(
        answers=[
            {"key": "must:Kafka", "grade": "strong", "quote": "budowałem integracje"},
            {
                "key": "must:Kubernetes",
                "grade": "weak",
                "quote": "Nie pracowałem z tym",
            },
            {"key": "q:999", "grade": "strong", "quote": "Mamy partycje"},
        ]
    )
    parsed = parse_review(raw, items=ITEMS, transcript=TRANSCRIPT)
    assert [a["key"] for a in parsed["answers"]] == [
        "must:Kafka",
        "must:Kubernetes",
        "q:7",
    ]
    assert parsed["answers"][2]["grade"] == "missing"


def test_lists_are_trimmed_to_three_lines() -> None:
    parsed = _parsed(went_well=["a", "b", "c", "d", 5, "  "])
    assert parsed["went_well"] == ["a", "b", "c"]


def test_garbage_output_raises_so_caller_marks_unavailable() -> None:
    with pytest.raises(ValueError):
        parse_review("brak JSON-a", items=ITEMS, transcript=TRANSCRIPT)


# ── Wynik i poziom ───────────────────────────────────────────────────────────


def test_total_is_weighted_by_settings_and_level_by_thresholds() -> None:
    score = score_review(
        _parsed(),
        config=cfg.defaults(),
        prep_no=1,
        talk_share=0.6,
        duration_seconds=30 * 60,
    )
    # tematy 50, must-have (100 + 0) / 2 = 50, pytania 50, udział 100.
    assert score.scores == {
        "topics": 50,
        "must_answers": 50,
        "client_questions": 50,
        "talk_share": 100,
    }
    assert score.total == round((50 * 25 + 50 * 40 + 50 * 20 + 100 * 15) / 100)
    assert score.level == "ok"


def test_criterion_without_points_drops_out_and_its_weight_spreads() -> None:
    # Bez mówców w transkrypcie (talk_share None) udział kandydata wypada.
    score = score_review(
        _parsed(),
        config=cfg.defaults(),
        prep_no=1,
        talk_share=None,
        duration_seconds=1800,
    )
    assert score.scores["talk_share"] is None
    assert "talk_share" not in score.weights_used
    assert score.total == 50


def test_answer_scale_points_come_from_settings() -> None:
    data = cfg.defaults().model_dump()
    data["answer_scale"]["general"]["points"] = 80
    data["answer_scale"]["weak"]["points"] = 40
    config = cfg.PrepReviewConfig.model_validate(data)
    score = score_review(
        _parsed(), config=config, prep_no=1, talk_share=None, duration_seconds=1800
    )
    assert score.scores["must_answers"] == 70
    assert score.scores["client_questions"] == 80


def test_too_short_prep_is_weak_unless_the_rule_is_off() -> None:
    parsed = _parsed()
    on = score_review(
        parsed, config=cfg.defaults(), prep_no=1, talk_share=None, duration_seconds=240
    )
    assert on.level == "weak" and "too_short" in on.caps
    off = score_review(
        parsed,
        config=_config(min_minutes_enabled=False),
        prep_no=1,
        talk_share=None,
        duration_seconds=240,
    )
    assert off.level == "ok"


def test_missing_required_topic_caps_good_at_ok() -> None:
    config = _config(good_threshold=50, weak_threshold=20)
    score = score_review(
        _parsed(), config=config, prep_no=1, talk_share=None, duration_seconds=1800
    )
    assert score.level == "ok"
    assert "required_topic_missing" in score.caps
    loose = _config(good_threshold=50, weak_threshold=20, required_topic_caps_ok=False)
    still = score_review(
        _parsed(), config=loose, prep_no=1, talk_share=None, duration_seconds=1800
    )
    assert "weak_must_answer" in still.caps and still.level == "ok"


# ── Notatka na Prep 2 i porównanie ───────────────────────────────────────────


def test_prep1_followup_lists_weak_then_missing_topic_then_general() -> None:
    followup = followup_items(_parsed(), cfg.defaults())
    assert [(f["label"], f["reason"]) for f in followup] == [
        ("Kubernetes", "weak"),
        ("Przebieg rozmowy u klienta", "missing_topic"),
        ("Jak skalujesz konsumentów?", "general"),
    ]
    assert followup[0]["note"] == "Przygotuj jeden przykład wdrożenia."


def test_followup_respects_switches_and_limit() -> None:
    data = cfg.defaults().model_dump()
    data["followup"].update({"general_answers": False, "max_items": 1})
    followup = followup_items(_parsed(), cfg.PrepReviewConfig.model_validate(data))
    assert [f["label"] for f in followup] == ["Kubernetes"]


def test_prep2_grades_followup_points_and_compares_with_prep1() -> None:
    prep1_followup = [
        {
            "key": "must:Kubernetes",
            "label": "Kubernetes",
            "kind": "must",
            "reason": "weak",
        },
        {
            "key": "topic:1",
            "label": "Przebieg rozmowy",
            "kind": "topic",
            "reason": "missing_topic",
        },
    ]
    items = [
        Item("topic:0", "Punkty z notatki na Prep 2", "topic", required=True),
        Item("followup:must:Kubernetes", "Kubernetes", "followup"),
        Item("followup:topic:1", "Przebieg rozmowy", "followup"),
    ]
    transcript = "Kandydat: Wdrożyłem klaster Kubernetes dla 30 serwisów sam."
    raw = json.dumps(
        {
            "summary": "Poprawa.",
            "topics": [
                {"key": "topic:0", "status": "covered", "quote": "Wdrożyłem klaster"}
            ],
            "answers": [
                {
                    "key": "followup:must:Kubernetes",
                    "grade": "strong",
                    "quote": "Wdrożyłem klaster Kubernetes dla 30 serwisów",
                },
                {"key": "followup:topic:1", "grade": "missing", "quote": None},
            ],
        }
    )
    parsed = parse_review(raw, items=items, transcript=transcript)
    rows = comparison(parsed, prep1_followup)
    assert [(r["label"], r["before"], r["after"]) for r in rows] == [
        ("Kubernetes", "weak", "strong"),
        ("Przebieg rozmowy", "missing_topic", "missing"),
    ]
    score = score_review(
        parsed, config=cfg.defaults(), prep_no=2, talk_share=None, duration_seconds=1200
    )
    assert score.scores["prep1_followup"] == 50
    assert set(score.scores) == set(cfg.PREP2_CRITERIA)


def test_prep2_question_already_strong_in_prep1_does_not_count() -> None:
    answers = [
        {"key": "q:7", "kind": "question", "grade": "missing"},
        {"key": "q:8", "kind": "question", "grade": "general"},
    ]
    marked = mark_covered_in_prep1(answers, {"q:7"})
    assert [a["grade"] for a in marked] == ["covered_in_prep1", "general"]


def test_prep1_followup_of_old_review_uses_remaining() -> None:
    class Old:
        criteria = {"items": []}
        remaining = ["Kubernetes", " "]

    assert prep1_followup_of(Old()) == [
        {"key": "v1:0", "label": "Kubernetes", "kind": "must", "reason": "missing"}
    ]
    assert prep1_followup_of(None) == []


def test_legacy_items_keep_the_window_before_v2_working() -> None:
    items = legacy_items(_parsed())
    assert [(i["key"], i["status"]) for i in items] == [
        ("must:Kafka", "covered"),
        ("must:Kubernetes", "partial"),
        ("q:7", "partial"),
    ]


# ── Prompt i notatka ─────────────────────────────────────────────────────────


def test_prompt_carries_topics_scale_and_fenced_hints() -> None:
    config = _config(ai_hints="Zwracaj uwagę na liczby.")
    items = [*topic_items(config, 1), *ITEMS[2:]]
    prompt = build_prompt(
        title="Java Developer",
        prep_no=1,
        items=items,
        config=config,
        transcript=TRANSCRIPT,
    )
    assert "topic:0" in prompt and "Klient i projekt" in prompt
    assert config.answer_scale["general"].description in prompt
    assert "Zwracaj uwagę na liczby." in prompt
    assert "punkty z notatki po Prepie 1" not in prompt


def test_note_has_facts_conclusions_and_followup_but_no_quotes() -> None:
    parsed = _parsed()
    text = note_content(
        prep_no=1,
        level="ok",
        total=56,
        parsed=parsed,
        talk_share=0.58,
        duration_seconds=31 * 60,
        followup=followup_items(parsed, cfg.defaults()),
        compared=[],
    )
    assert "Ocena: OK (56%)" in text
    assert "tematy 1/2" in text
    assert "odpowiedzi: 1 mocne, 1 ogólne, 1 słabe" in text
    assert "kandydat mówił 58% czasu" in text
    assert "Nie tak: Kubernetes bez przykładu" in text
    assert "Do powtórzenia na Prep 2: 1) Kubernetes — słaba odpowiedź" in text
    assert "budowałem integracje" not in text


def test_prep2_note_shows_before_and_after() -> None:
    text = note_content(
        prep_no=2,
        level="good",
        total=88,
        parsed={**_parsed(), "topics": []},
        talk_share=None,
        duration_seconds=18 * 60,
        followup=[],
        compared=[{"label": "Kubernetes", "before": "weak", "after": "strong"}],
    )
    assert "Punkty z Prepu 1: Kubernetes: słaba odpowiedź → mocna" in text


def test_note_when_ai_is_unavailable_has_no_grade() -> None:
    text = note_content(
        prep_no=2,
        level=None,
        total=None,
        parsed=None,
        talk_share=None,
        duration_seconds=25 * 60,
        followup=[],
        compared=[],
    )
    assert "Ocena" not in text
    assert "niedostępne" in text
