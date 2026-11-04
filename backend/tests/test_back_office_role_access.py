"""Rola „Back office” (0644): zamówienia i umowy bez finansów firmy.

Obietnica z decyzji Artura (04.11.2026): osoba od zamówień i umów pracuje na
kontraktach, zamówieniach i stawkach przy rekordzie, a Wyników miesięcznych,
Płac, faktur i czatów całej firmy nie widzi. Test czyta wzorzec bramek
``tests/data/authz_golden/`` (kolumna persony ``back_office``).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.analytics.capabilities import AnalyticsCapability, capabilities_for
from app.models.user import User, UserRole
from app.services.back_office.access import default_teams
from app.services.hr.payroll_access import is_payroll
from app.services.permission_catalog import close, default_permissions_for_role

GOLDEN = Path(__file__).parent / "data" / "authz_golden"
PASSES = frozenset("PB")
PERSONA = "back_office"


def _verdicts() -> dict[str, str]:
    verdicts: dict[str, str] = {}
    for path in GOLDEN.glob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        personas = payload["personas"]
        index = personas.index(PERSONA)
        for route, letters in payload["routes"].items():
            verdicts[route] = letters[index]
    return verdicts


@pytest.mark.parametrize(
    "route",
    [
        "GET /api/finance/order-changes",
        "GET /api/finance/order-changes/summary",
        "POST /api/finance/order-changes/checks",
        "GET /api/finance/order-pdfs",
        "GET /api/finance/order-pdfs/months",
        "POST /api/md-consumption/imports",
        "GET /api/md-consumption/imports",
        "GET /api/contracts",
        "POST /api/contracts",
    ],
)
def test_opens_the_work_on_orders_and_contracts(route: str) -> None:
    assert _verdicts()[route] in PASSES, route


@pytest.mark.parametrize(
    "route",
    [
        # Wyniki miesięczne i Archiwum.
        "GET /api/finance/results",
        "GET /api/finance/periods",
        "GET /api/finance/imports",
        # Czaty całej firmy.
        "GET /api/admin/global-chats",
        # Wyniki firmy.
        "GET /api/dashboard/v2/finance",
        "GET /api/invoices/dso",
    ],
)
def test_keeps_company_money_closed(route: str) -> None:
    verdicts = _verdicts()
    if route not in verdicts:
        pytest.fail(f"Trasy {route} nie ma we wzorcu")
    assert verdicts[route] == "D", route


def test_payroll_stays_closed_at_the_handler_gate() -> None:
    # Trasy /api/hr/payroll rozstrzygają o dostępie w handlerze (is_payroll),
    # więc macierz zależności ich nie widzi.
    assert is_payroll(_user()) is False


def _user() -> User:
    return User(id=1, role=UserRole.back_office, roles=[UserRole.back_office.value])


def test_role_defaults_hold_the_work_and_no_company_money() -> None:
    held = default_permissions_for_role("back_office")
    assert {
        "delivery_view",
        "clients_edit",
        "contracts_orders_edit",
        "contract_status",
        "b2b_signature_confirmation",
        "amounts_view",
        "amounts_edit",
        "orders_work",
    } == set(held)


def test_section_finance_stays_closed_so_view_finance_is_not_granted() -> None:
    caps = capabilities_for(_user())
    assert AnalyticsCapability.VIEW_FINANCE not in caps
    assert AnalyticsCapability.MANAGE_FINANCE not in caps
    assert AnalyticsCapability.VIEW_EXECUTIVE not in caps


def test_finance_module_implies_orders_work_for_grant_holders() -> None:
    assert "orders_work" in close(("finance_module",))


def test_back_office_board_puts_the_role_in_contract_and_order_teams() -> None:
    assert default_teams(_user()) == frozenset({"contracts", "orders"})


def test_order_change_checkboxes_are_active_for_the_role() -> None:
    # Ekran pyta ``can_check``; bez tego Back office widziałby nieaktywne pola,
    # choć ``POST /order-changes/checks`` go przepuszcza.
    from types import SimpleNamespace

    from app.api.finance import _can_check

    request = SimpleNamespace(state=SimpleNamespace(impersonator_id=None))
    assert _can_check(request, _user()) is True

    impersonated = SimpleNamespace(state=SimpleNamespace(impersonator_id=5))
    assert _can_check(impersonated, _user()) is False
