"""Ustawienia oceny prepów (0505) — walidacja i progi w ocenie, bez bazy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.prep_meeting import PrepReviewConfigVersion
from app.services import prep_review_config as cfg
from app.services.prep_review_scoring import score_review


def _with(**changes) -> dict:
    data = cfg.defaults().model_dump()
    data.update(changes)
    return data


def test_defaults_reproduce_env_thresholds_and_question_limit() -> None:
    d = cfg.defaults()
    assert d.good_threshold == round(settings.PREP_REVIEW_GOOD_COVERAGE * 100)
    assert d.weak_threshold == round(settings.PREP_REVIEW_WEAK_COVERAGE * 100)
    assert d.min_minutes == settings.PREP_REVIEW_MIN_MINUTES
    assert d.max_client_questions == 20
    assert sum(d.prep1.weights.values()) == 100
    assert sum(d.prep2.weights.values()) == 100


def test_weights_must_sum_to_100() -> None:
    data = _with()
    data["prep1"]["weights"]["topics"] = 30
    with pytest.raises(ValidationError, match="100%"):
        cfg.PrepReviewConfig.model_validate(data)


def test_unknown_criterion_is_refused() -> None:
    data = _with()
    data["prep2"]["weights"] = {"topics": 100}
    with pytest.raises(ValidationError, match="kryteria"):
        cfg.PrepReviewConfig.model_validate(data)


def test_weak_threshold_below_good() -> None:
    with pytest.raises(ValidationError, match="niższy"):
        cfg.PrepReviewConfig.model_validate(_with(good_threshold=60, weak_threshold=60))


def test_answer_scale_points_cannot_grow() -> None:
    data = _with()
    data["answer_scale"]["general"]["points"] = 100
    data["answer_scale"]["strong"]["points"] = 80
    with pytest.raises(ValidationError, match="nie mogą rosnąć"):
        cfg.PrepReviewConfig.model_validate(data)


def test_duplicate_topic_is_refused() -> None:
    data = _with()
    data["prep1"]["topics"].append({"label": "stawka i DOSTĘPNOŚĆ", "required": True})
    with pytest.raises(ValidationError, match="dwa razy"):
        cfg.PrepReviewConfig.model_validate(data)


def test_stored_version_without_new_key_gets_default() -> None:
    stored = _with()
    del stored["ai_hints"]
    row = PrepReviewConfigVersion(id=3, config=stored)
    assert cfg._from_row(row).ai_hints == ""


def test_describe_changes_names_threshold_and_weight() -> None:
    before = _with()
    after = _with(good_threshold=85)
    after["prep1"]["weights"].update({"topics": 30, "must_answers": 35})
    changes = cfg.describe_changes(before, after)
    assert "Dobry od: 80% → 85%" in changes
    assert "Prep 1 · Tematy prowadzącego: 25% → 30%" in changes


def _parsed(must_grades: list[str]) -> dict:
    return {
        "topics": [],
        "answers": [
            {"key": f"must:{i}", "label": f"M{i}", "kind": "must", "grade": g}
            for i, g in enumerate(must_grades)
        ],
    }


def test_score_uses_published_thresholds() -> None:
    config = cfg.PrepReviewConfig.model_validate(
        _with(good_threshold=60, weak_threshold=30)
    )
    # Dwie mocne, jedna nie było = 67%: przy startowych progach „OK”, przy 60% „dobry”.
    parsed = _parsed(["strong", "strong", "missing"])
    kwargs = dict(prep_no=1, talk_share=None, duration_seconds=1800)
    assert score_review(parsed, config=cfg.defaults(), **kwargs).level == "ok"
    assert score_review(parsed, config=config, **kwargs).level == "good"


def test_talk_share_criterion_can_be_switched_off() -> None:
    config = cfg.PrepReviewConfig.model_validate(_with(talk_share_enabled=False))
    parsed = _parsed(["strong"])
    kwargs = dict(prep_no=1, talk_share=0.1, duration_seconds=1800)
    assert (
        score_review(parsed, config=cfg.defaults(), **kwargs).scores["talk_share"] == 22
    )
    off = score_review(parsed, config=config, **kwargs)
    assert off.scores["talk_share"] is None and off.level == "good"


# --- Przygotowanie: fundamenty prepa (F1, decyzje Artura 24.11.2026) -------


def test_default_preparation_has_18_fundamentals_with_stop_conditions_first() -> None:
    prep = cfg.defaults().preparation
    items = [i for g in prep.groups for i in g.items]
    assert len(prep.groups) == 5
    assert len(items) == 18
    # Warunki stop to dokładnie grupa A (forma, stawka, dostępność, tryb pracy).
    assert [i.stop for i in prep.groups[0].items] == [True] * 4
    assert not any(i.stop for g in prep.groups[1:] for i in g.items)
    assert all(i.says and i.passed_when for i in items)
    assert len(prep.readiness) == 5


def test_default_preparation_uses_brand_spelling() -> None:
    text = str(cfg.defaults().preparation.model_dump())
    assert "B2Bnetwork" in text
    assert "B2B.net" not in text and "B2B Network" not in text


def test_stored_version_without_preparation_gets_the_18_points() -> None:
    stored = _with()
    del stored["preparation"]
    row = PrepReviewConfigVersion(id=2, config=stored)
    assert cfg._from_row(row).preparation == cfg.default_preparation()


def test_duplicate_fundamental_is_refused_across_groups() -> None:
    data = _with()
    data["preparation"]["groups"][4]["items"].append(
        {"label": "stawka ", "says": "", "passed_when": "", "stop": False}
    )
    with pytest.raises(ValidationError, match="dwa razy"):
        cfg.PrepReviewConfig.model_validate(data)


def test_blank_fundamental_label_is_refused() -> None:
    data = _with()
    data["preparation"]["groups"][1]["items"][0]["label"] = "   "
    with pytest.raises(ValidationError, match="musi mieć nazwę"):
        cfg.PrepReviewConfig.model_validate(data)


def test_preparation_limits() -> None:
    data = _with()
    data["preparation"]["readiness"] = ["Punkt gotowości"] * (cfg.MAX_READINESS + 1)
    with pytest.raises(ValidationError):
        cfg.PrepReviewConfig.model_validate(data)
    data = _with()
    data["preparation"]["readiness"] = ["  ok  "]  # po obcięciu spacji 2 znaki
    with pytest.raises(ValidationError):
        cfg.PrepReviewConfig.model_validate(data)


def test_empty_preparation_is_allowed() -> None:
    data = _with()
    data["preparation"] = {"groups": [], "readiness": []}
    assert cfg.PrepReviewConfig.model_validate(data).preparation.groups == []


def test_describe_changes_preparation_only_when_it_changed() -> None:
    # Wersja sprzed klucza `preparation` (np. v2 z 28.10) nie ma go w JSON-ie:
    # publikacja samych progów nie może pokazać „fundamenty zmienione”.
    before = _with()
    del before["preparation"]
    assert not any(
        c.startswith("Przygotowanie")
        for c in cfg.describe_changes(before, _with(good_threshold=85))
    )
    after = _with()
    after["preparation"]["groups"][3]["items"].pop()
    after["preparation"]["readiness"].append("Opowiedzieć o sobie po angielsku")
    changes = cfg.describe_changes(before, after)
    assert "Przygotowanie · fundamenty zmienione (17 punktów)" in changes
    assert "Przygotowanie · „kandydat po przygotowaniu umie” zmienione" in changes
