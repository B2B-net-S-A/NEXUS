"""Ustawienia oceny prepów (0505) — walidacja i progi w ocenie, bez bazy."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import settings
from app.models.prep_meeting import PrepReviewConfigVersion
from app.services import prep_review_config as cfg
from app.services.prep_review import grade


def _items(covered: int, missing: int) -> list[dict]:
    return [
        {"key": f"must:{i}", "label": f"M{i}", "kind": "must", "status": "covered"}
        for i in range(covered)
    ] + [
        {"key": f"q:{i}", "label": f"Q{i}", "kind": "question", "status": "missing"}
        for i in range(missing)
    ]


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


def test_grade_uses_published_thresholds() -> None:
    config = cfg.PrepReviewConfig.model_validate(
        _with(good_threshold=60, weak_threshold=30)
    )
    # pokrycie 2/3 = 67%: przy startowych progach „OK”, przy 60% „dobry”.
    items = _items(covered=2, missing=1)
    kwargs = dict(talk_share=None, duration_seconds=1800, own_projects_told=True)
    assert grade(items, **kwargs).level == "ok"
    assert grade(items, **kwargs, config=config).level == "good"


def test_grade_min_minutes_rule_can_be_switched_off() -> None:
    config = cfg.PrepReviewConfig.model_validate(_with(min_minutes_enabled=False))
    items = _items(covered=3, missing=0)
    kwargs = dict(talk_share=None, duration_seconds=240, own_projects_told=True)
    assert grade(items, **kwargs).level == "weak"
    assert grade(items, **kwargs, config=config).level == "good"


def test_grade_talk_share_criterion_can_be_switched_off() -> None:
    config = cfg.PrepReviewConfig.model_validate(_with(talk_share_enabled=False))
    items = _items(covered=3, missing=0)
    kwargs = dict(talk_share=0.1, duration_seconds=1800, own_projects_told=True)
    assert grade(items, **kwargs).level == "weak"
    assert grade(items, **kwargs, config=config).level == "good"
