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


def test_placements_sheet_can_drop_the_margin_columns() -> None:
    from app.services import contract_placements_export as placements

    row = list(range(len(placements.PLACEMENT_EXPORT_COLUMNS)))
    columns, rows = placements.without_margin_columns([row])

    assert "Marża" not in columns and "Marża mies." not in columns
    assert "Stawka przychodowa" in columns
    assert len(rows[0]) == len(columns) == len(row) - 2


def test_list_row_loses_margin_but_keeps_rates() -> None:
    from types import SimpleNamespace

    from app.api.contracts import _hide_company_margin

    member = SimpleNamespace(margin=10, rate_client=100)
    item = SimpleNamespace(
        margin=10, monthly_margin=1680, rate_client=100, group_members=[member]
    )

    _hide_company_margin(item)

    assert item.margin is None and item.monthly_margin is None
    assert member.margin is None
    assert item.rate_client == 100 and member.rate_client == 100


@pytest.mark.asyncio
async def test_whole_company_export_needs_the_permission() -> None:
    from app.api.contracts import export_contracts

    with pytest.raises(HTTPException) as denied:
        await export_contracts(
            current_user=_account(UserRole.finance, FM),
            db=None,
            format="xlsx",
            q=None,
            status=None,
            client_id=None,
            candidate_id=None,
            contract_type=None,
            start_from=None,
            start_to=None,
            end_from=None,
            end_to=None,
            period_from=None,
            period_to=None,
            subcategory=None,
            rate_client_min=None,
            rate_client_max=None,
            margin_min=None,
            expiring_in_days=None,
            order_end_from=None,
            order_end_to=None,
            agreement_not_terminated=False,
            limit=10,
        )
    assert denied.value.status_code == 403


@pytest.mark.asyncio
async def test_month_sum_of_invoices_is_hidden_without_the_permission(
    monkeypatch,
) -> None:
    from app.api import client_sales_invoices as invoices

    async def month_view(_db, **_kwargs):
        return {
            "period": "2026-10",
            "invoices": [{"id": 1}],
            "summary": {
                "rows": 3,
                "expected": [{"amount": "100", "currency": "PLN"}],
                "invoiced_net": [{"amount": "90", "currency": "PLN"}],
            },
        }

    async def module_open(_db, _user):
        return True

    monkeypatch.setattr(invoices.views, "month_view", month_view)
    monkeypatch.setattr(invoices, "_module_open", module_open)

    finance = await invoices.finance_invoices(
        _account(UserRole.finance, FM), db=None, year=2026, month=10
    )
    assert finance["summary"]["expected"] == []
    assert finance["summary"]["invoiced_net"] == []
    assert finance["summary"]["totals_hidden"] is True
    assert finance["invoices"] == [{"id": 1}]

    holder = await invoices.finance_invoices(
        _account(UserRole.finance, FM, CR), db=None, year=2026, month=10
    )
    assert holder["summary"]["expected"] == [{"amount": "100", "currency": "PLN"}]
