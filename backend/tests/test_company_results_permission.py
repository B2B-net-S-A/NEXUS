"""„Wyniki firmy”: zbiorcze kwoty firmy dla Rady, admina i osoby z nadaniem.

Decyzja Artura 02.11.2026: Finanse pracują na pojedynczych rekordach. „Moduł
Finanse” otwiera ich narzędzia, ale nie podsumowanie całej firmy.
"""

from __future__ import annotations

import random
from typing import get_args, get_type_hints

import pytest
from fastapi import HTTPException

import app.models  # noqa: F401
from app.api import insights_board
from app.models.user import User, UserRole
from app.services import action_permissions as actions
from app.services import permission_catalog as catalog
from app.services.custom_metrics import engine

CR = catalog.COMPANY_RESULTS
FM = catalog.FINANCE_MODULE
AV = catalog.AMOUNTS_VIEW


def _account(role: UserRole, *permissions: str) -> User:
    user = User(
        id=random.randint(1, 10**6),
        email=f"cr-{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
    )
    held = catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = {
        **catalog.derive_sections(held),
        "insights": "read",
    }
    return user


def _gate(route):
    annotation = get_type_hints(route, include_extras=True)["current_user"]
    return get_args(annotation)[1].dependency


def test_nobody_holds_the_permission_by_default() -> None:
    assert CR in catalog.KEYS
    assert catalog.label(CR).startswith("Wyniki firmy")
    # Bez zależności: nadanie nie otwiera przy okazji kontraktów ani Delivery.
    assert catalog.close([CR]) == frozenset({CR})
    assert CR not in catalog.default_permissions_for_role("finance")


def test_money_on_the_board_is_for_the_board_and_the_holder() -> None:
    assert actions.reads_board_money(_account(UserRole.board))
    assert actions.reads_board_money(_account(UserRole.finance, CR))
    assert actions.reads_board_money(_account(UserRole.recruiter, CR))
    assert not actions.reads_board_money(_account(UserRole.finance, FM))
    assert not actions.reads_board_money(_account(UserRole.head_of_recruitment))


@pytest.mark.asyncio
async def test_firma_refuses_the_finance_module_alone() -> None:
    gate = _gate(insights_board.insights_board)

    for allowed in (_account(UserRole.board), _account(UserRole.finance, CR)):
        assert await gate(allowed) is allowed

    with pytest.raises(HTTPException) as denied:
        await gate(_account(UserRole.finance, FM))
    assert denied.value.status_code == 403
    assert catalog.label(CR) in str(denied.value.detail)


@pytest.mark.asyncio
async def test_year_on_year_stays_open_to_finance_without_money() -> None:
    gate = _gate(insights_board.insights_board_yoy)
    finance = _account(UserRole.finance, FM)

    assert await gate(finance) is finance
    assert not actions.reads_board_money(finance)
    # Osoba z samym nadaniem też ma tabelę, już z kwotami.
    holder = _account(UserRole.recruiter, CR)
    assert await gate(holder) is holder


def test_metric_builder_keeps_the_portfolio_but_not_the_whole_company() -> None:
    finance = _account(UserRole.finance, FM)
    amounts_only = _account(UserRole.recruiter, AV)
    lead = _account(UserRole.delivery_lead, AV)
    holder = _account(UserRole.recruiter, CR)

    assert engine.source_denial(finance, "finance") is not None
    assert engine.source_denial(amounts_only, "finance") is not None
    assert engine.source_denial(lead, "finance") is None
    assert engine.source_denial(holder, "finance") is None


@pytest.mark.asyncio
async def test_whole_company_scope_needs_the_permission() -> None:
    holder = _account(UserRole.recruiter, CR)
    assert await engine._finance_client_boundary(holder, db=None) is None

    with pytest.raises(engine.MetricAccessDenied):
        await engine._finance_client_boundary(_account(UserRole.finance, FM), db=None)
