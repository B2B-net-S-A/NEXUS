"""Przewodniki ekranów: przycisk dla posiadaczy uprawnienia idzie za uprawnieniem.

Lista ról w ``requires`` przestaje być prawdą, gdy administrator przełączy
pozycję na ekranie „Osoby i role” — Jarvis wskazywałby wtedy przycisk, którego
osoba nie ma, albo przemilczał taki, który dostała.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.data.screen_guides import AnchorRequires, guide_for_user, load_guides

ALL_SECTIONS = {
    section: 2 for section in ("sourcing", "pipeline", "delivery", "insights")
}


def _anchor_ids(key: str, *, roles: set[str], permissions: set[str]) -> set[str]:
    shaped = guide_for_user(load_guides()[key], roles, ALL_SECTIONS, permissions)
    assert shaped is not None
    return {anchor["id"] for anchor in shaped["anchors"]}


def test_new_recruitment_button_follows_the_permission_not_the_role() -> None:
    # Delivery Lead z wyłączoną pozycją przycisku nie ma…
    assert "jobs.list.new" not in _anchor_ids(
        "jobs.list", roles={"delivery_lead"}, permissions=set()
    )
    # …a rekruter, któremu ją nadano — ma.
    assert "jobs.list.new" in _anchor_ids(
        "jobs.list", roles={"recruiter"}, permissions={"recruitment_manage"}
    )


def test_new_order_button_follows_contracts_and_orders_edit() -> None:
    assert "client.orders.new" in _anchor_ids(
        "client.orders",
        roles={"finance"},
        permissions={"delivery_view", "contracts_orders_edit"},
    )
    assert "client.orders.new" not in _anchor_ids(
        "client.orders",
        roles={"talent_community_manager"},
        permissions={"delivery_view", "contract_status"},
    )


def test_a_task_pointing_at_a_hidden_button_loses_its_anchor() -> None:
    guide = load_guides()["jobs.list"]
    shaped = guide_for_user(guide, {"recruiter"}, ALL_SECTIONS, set())
    assert shaped is not None
    visible = {anchor["id"] for anchor in shaped["anchors"]}
    assert all(task["anchor"] in visible | {None} for task in shaped["tasks"])


def test_unknown_permission_in_a_guide_fails_loudly() -> None:
    """Literówka ukryłaby kotwicę każdemu, więc plik ma nie przejść walidacji."""

    with pytest.raises(ValidationError):
        AnchorRequires(permissions=["recruitment_mange"])
    assert AnchorRequires(permissions=["recruitment_manage"]).permissions == [
        "recruitment_manage"
    ]
