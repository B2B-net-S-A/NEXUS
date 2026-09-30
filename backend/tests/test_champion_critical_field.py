"""Pole „Krytyczne (0–2)” w profilu Championa (30.09.2026)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.schemas.champion import ChampionProfile, ChampionStack
from app.services.champion_intake import copy_profile, user_edit
from app.services.champion_view import requirement_source
from tests.taxonomy_fixture import hydrated_taxonomy


def _profile(**stack):
    return {"stack": {"must": [{"name": "Java"}, {"name": "Kafka"}], **stack}}


def test_undecided_is_absent_from_the_stored_json():
    dumped = ChampionProfile.model_validate(_profile()).model_dump(mode="json")
    assert "critical" not in dumped["stack"]


def test_explicit_empty_list_is_kept_as_a_decision():
    dumped = ChampionProfile.model_validate(_profile(critical=[])).model_dump(
        mode="json"
    )
    assert dumped["stack"]["critical"] == []


def test_names_are_trimmed_and_deduplicated():
    stack = ChampionStack.model_validate(
        {"critical": ["  Java ", "java", {"name": "Kafka"}]}
    )
    assert stack.critical == ["Java", "Kafka"]


def test_more_than_two_is_rejected():
    with pytest.raises(ValidationError):
        ChampionStack.model_validate({"critical": ["Java", "Kafka", "Docker"]})


def test_critical_does_not_change_the_requirement_source():
    before = ChampionProfile.model_validate(_profile()).model_dump(mode="json")
    after = ChampionProfile.model_validate(_profile(critical=["Java"])).model_dump(
        mode="json"
    )
    assert requirement_source(before) == requirement_source(after)


def test_saving_only_critical_keeps_the_intake_stamp():
    stored = user_edit({}, _profile(), actor_id=1)
    edited = user_edit(stored, {"stack": {"critical": ["Java"]}}, actor_id=1)
    assert edited["stack"]["critical"] == ["Java"]
    assert edited.get("intake") == stored.get("intake")


def test_patch_without_critical_keeps_the_stored_choice():
    stored = user_edit({}, _profile(critical=["Kafka"]), actor_id=1)
    edited = user_edit(stored, {"stack": {"notes": "Java 17+"}}, actor_id=1)
    assert edited["stack"]["critical"] == ["Kafka"]


def test_template_copy_waits_for_its_own_decision():
    stored = user_edit({}, _profile(critical=["Java"]), actor_id=1)
    copied = copy_profile(stored, actor_id=2)
    assert "critical" not in copied["stack"]


def test_critical_errors_explain_in_polish():
    from app.services.critical_skills import critical_errors

    with hydrated_taxonomy():
        assert critical_errors(["Java"], ["Java", "QA"]) == []
        codes = [c for c, _ in critical_errors(["Python", "QA"], ["Java", "QA"])]
        assert codes == ["critical_not_in_must", "critical_not_technology"]


def test_removing_a_must_item_drops_it_from_critical():
    stored = user_edit({}, _profile(critical=["Java", "Kafka"]), actor_id=1)
    edited = user_edit(stored, {"stack": {"must": [{"name": "Kafka"}]}}, actor_id=1)
    assert edited["stack"]["critical"] == ["Kafka"]


def test_losing_every_critical_returns_the_decision_to_the_dl():
    stored = user_edit({}, _profile(critical=["Java"]), actor_id=1)
    edited = user_edit(stored, {"stack": {"must": [{"name": "Kafka"}]}}, actor_id=1)
    assert "critical" not in edited["stack"]
