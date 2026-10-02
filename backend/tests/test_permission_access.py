"""Bramka trasy pytająca o uprawnienie i odmowa z jego nazwą."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.financial_access import (
    assert_amounts_only,
    can_manage_finance_amounts,
    can_read_client_finance,
    can_write_order_amounts,
    order_amounts_denied,
)
from app.api.permission_access import (
    PERMISSION_DENIED_CODE,
    require_any_permission,
    require_permission,
)
from app.models.user import UserRole
from app.services.action_permissions import ProductAction


def _user(*roles: UserRole, permissions: tuple[str, ...] = (), user_id: int = 17):
    role_set = set(roles)
    user = SimpleNamespace(
        id=user_id,
        get_all_roles=lambda: role_set,
        has_role=lambda role: role in role_set,
        has_any_role=lambda *required: bool(role_set.intersection(required)),
    )
    user.effective_action_access = {key: "manage" for key in permissions}
    user.effective_section_access = {}
    return user


async def test_route_gate_names_the_missing_permission() -> None:
    gate = require_permission(ProductAction.contracts_orders_edit)
    tcm = _user(UserRole.talent_community_manager, permissions=("delivery_view",))

    with pytest.raises(HTTPException) as denied:
        await gate(tcm)

    assert denied.value.status_code == 403
    assert denied.value.detail == {
        "code": PERMISSION_DENIED_CODE,
        "permission": "contracts_orders_edit",
        "label": "Kontrakty i zamówienia: tworzenie i edycja",
        "permissions": ["contracts_orders_edit"],
        "message": (
            "Brakuje Ci uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”. "
            "Poproś administratora o dostęp."
        ),
    }


async def test_route_gate_lets_the_holder_through_whatever_the_role() -> None:
    gate = require_permission(ProductAction.contracts_orders_edit)
    tcm = _user(
        UserRole.talent_community_manager,
        permissions=("delivery_view", "contracts_orders_edit"),
    )

    assert await gate(tcm) is tcm


async def test_any_permission_gate_lists_both_names() -> None:
    gate = require_any_permission(
        ProductAction.contracts_orders_edit, ProductAction.amounts_edit
    )
    finance = _user(UserRole.finance, permissions=("amounts_edit",))
    assert await gate(finance) is finance

    with pytest.raises(HTTPException) as denied:
        await gate(_user(UserRole.recruiter))
    assert denied.value.detail["permissions"] == [
        "contracts_orders_edit",
        "amounts_edit",
    ]
    assert " albo " in denied.value.detail["message"]

    with pytest.raises(ValueError):
        require_any_permission()


def test_route_gates_are_recognised_by_the_authz_contract() -> None:
    from tests.test_route_authz_contract import _GATE_QUALNAME_MARKERS

    for gate in (
        require_permission(ProductAction.delivery_view),
        require_any_permission(ProductAction.delivery_view),
    ):
        assert any(marker in gate.__qualname__ for marker in _GATE_QUALNAME_MARKERS)


def test_amounts_of_a_client_follow_the_view_permission_and_the_portfolio() -> None:
    lead = _user(UserRole.delivery_lead, permissions=("amounts_view",))
    assert can_read_client_finance(
        lead, client_id=5, delivery_lead_finance_client_ids=frozenset({5})
    )
    assert not can_read_client_finance(
        lead, client_id=6, delivery_lead_finance_client_ids=frozenset({5})
    )
    # Konto rządzone portfelem DL bez podanej granicy = błąd wołającego.
    assert not can_read_client_finance(
        lead, client_id=5, delivery_lead_finance_client_ids=None
    )

    # Wyłączony przełącznik odbiera kwoty także u własnego klienta.
    lead_without = _user(UserRole.delivery_lead)
    assert not can_read_client_finance(
        lead_without, client_id=5, delivery_lead_finance_client_ids=frozenset({5})
    )

    # Posiadacz bez roli DL widzi kwoty każdego klienta.
    holder = _user(UserRole.talent_community_manager, permissions=("amounts_view",))
    assert can_read_client_finance(
        holder, client_id=6, delivery_lead_finance_client_ids=None
    )
    assert not can_read_client_finance(
        _user(UserRole.talent_community_manager),
        client_id=6,
        delivery_lead_finance_client_ids=None,
    )


def test_contract_amounts_need_the_edit_permission_inside_the_portfolio() -> None:
    finance = _user(UserRole.finance, permissions=("amounts_view", "amounts_edit"))
    assert can_manage_finance_amounts(finance)

    lead = _user(UserRole.delivery_lead, permissions=("amounts_view", "amounts_edit"))
    assert not can_manage_finance_amounts(lead)
    assert can_manage_finance_amounts(
        lead, client_id=5, delivery_lead_finance_client_ids=frozenset({5})
    )
    assert not can_manage_finance_amounts(
        lead, client_id=6, delivery_lead_finance_client_ids=frozenset({5})
    )
    assert not can_manage_finance_amounts(_user(UserRole.delivery_lead))


def test_order_amounts_stay_with_the_assigned_delivery_lead() -> None:
    lead = _user(
        UserRole.delivery_lead, permissions=("contracts_orders_edit", "amounts_view")
    )
    assert can_write_order_amounts(
        lead, client_id=5, delivery_lead_finance_client_ids=frozenset({5})
    )
    assert not can_write_order_amounts(
        lead, client_id=6, delivery_lead_finance_client_ids=frozenset({5})
    )
    out_of_portfolio = order_amounts_denied(lead)
    assert out_of_portfolio.detail == "Ten klient jest poza Twoim portfelem."

    # Sandra: zakłada zamówienia, ale bez podglądu kwot nie wpisze stawek.
    tcm = _user(
        UserRole.talent_community_manager,
        permissions=("delivery_view", "contracts_orders_edit"),
    )
    assert not can_write_order_amounts(
        tcm, client_id=5, delivery_lead_finance_client_ids=None
    )
    assert order_amounts_denied(tcm).detail["permission"] == "amounts_view"

    recruiter = _user(UserRole.recruiter)
    assert order_amounts_denied(recruiter).detail["permission"] == "amounts_edit"


def test_amount_editor_without_record_edit_touches_only_amounts() -> None:
    assert_amounts_only({"rate_client", "notes"}, {"rate_client"}, can_edit_record=True)
    assert_amounts_only({"rate_client"}, {"rate_client"}, can_edit_record=False)

    with pytest.raises(HTTPException) as denied:
        assert_amounts_only(
            {"rate_client", "notes"}, {"rate_client"}, can_edit_record=False
        )
    assert denied.value.status_code == 403
    assert denied.value.detail["code"] == "finance_amounts_only"
    assert denied.value.detail["fields"] == ["notes"]
