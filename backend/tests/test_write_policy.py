"""``WritePolicy`` — jedno ciało zapisu dla ekranu i API v1 (PR 2B, bez bazy).

Trzy własności, na których stoi wydzielenie ciał ``apply_*``:

* ``UserWritePolicy`` woła bramki ekranu z DOKŁADNIE tymi argumentami, co
  handler przed wydzieleniem (zachowanie ekranu bez zmian),
* ``IntegrationWritePolicy`` decyduje wyłącznie ze scope'ów klucza i nigdy nie
  pyta o uprawnienia osoby (konto serwisowe nie udaje ``User``),
* trasy ekranu budują politykę osoby, trasy v1 — politykę konta.
"""

from __future__ import annotations

import ast
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api import client_order_groups, client_orders, contracts
from app.api import write_policy as policy_module
from app.api.client_orders import _OrderAmounts
from app.api.write_policy import IntegrationWritePolicy, UserWritePolicy
from app.models.service_account import ServiceScope, implied_scopes
from app.models.user import User, UserRole
from app.schemas.contract import ContractUpdate
from app.services.integration_actor import IntegrationActor
from app.services.service_account_auth import ServicePrincipal

_APP = Path(__file__).resolve().parents[1] / "app"


def _user() -> User:
    return User(
        id=41,
        email="dl@example.com",
        name="Osoba Testowa",
        role=UserRole.delivery_lead,
        roles=[UserRole.delivery_lead.value],
        is_active=True,
    )


def _principal(*scopes: str) -> ServicePrincipal:
    return ServicePrincipal(
        account_id=7,
        slug="rozliczenia",
        key_id="v2$00",
        scopes=implied_scopes(frozenset(scopes)),
        name="Rozliczenia",
    )


class _Spy:
    def __init__(self, result=None) -> None:
        self.calls: list[tuple[tuple, dict]] = []
        self.result = result

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.result


class _AsyncSpy(_Spy):
    async def __call__(self, *args, **kwargs):  # type: ignore[override]
        self.calls.append((args, kwargs))
        return self.result


async def _refuse(*_args, **_kwargs):
    raise AssertionError("polityka konta nie może wołać bramek osoby")


# ── UserWritePolicy: bramki ekranu bez zmian ────────────────────────────────


async def test_user_policy_calls_the_screen_gates_with_the_original_arguments(
    monkeypatch,
) -> None:
    user, db = _user(), object()
    policy = UserWritePolicy(user, db)  # type: ignore[arg-type]

    lifecycle = _AsyncSpy()
    monkeypatch.setattr(client_order_groups, "_require_order_lifecycle", lifecycle)
    await policy.require_order_lifecycle(5)
    await policy.require_order_lifecycle(5, for_write=True)
    assert lifecycle.calls == [
        ((db, user, 5), {"for_write": False}),
        ((db, user, 5), {"for_write": True}),
    ]

    line_amounts = _AsyncSpy()
    monkeypatch.setattr(
        client_order_groups, "_assert_line_finance_write_allowed", line_amounts
    )
    await policy.assert_line_amounts_writable(5, {"rate_cost"})
    assert line_amounts.calls == [((db, user, 5, {"rate_cost"}), {})]

    file_read = _AsyncSpy()
    monkeypatch.setattr(client_orders, "_require_order_file_read", file_read)
    await policy.require_order_file(5)
    assert file_read.calls == [((db, user, 5), {})]

    contract = SimpleNamespace(client_id=5)
    visible = _AsyncSpy()
    monkeypatch.setattr(contracts, "_ensure_delivery_lead_contract_visible", visible)
    await policy.assert_contract_visible(contract)  # type: ignore[arg-type]
    assert visible.calls == [((contract, user, db), {})]

    contract_amounts = _AsyncSpy()
    monkeypatch.setattr(
        contracts, "_assert_contract_finance_write_allowed", contract_amounts
    )
    await policy.assert_contract_amounts_writable({"end_date"}, client_id=5)
    assert contract_amounts.calls == [
        ((user, {"end_date"}), {"client_id": 5, "db": db})
    ]

    status_change = _Spy()
    monkeypatch.setattr(
        contracts, "_assert_contract_status_change_allowed", status_change
    )
    data = ContractUpdate(end_date=date(2042, 6, 30))
    policy.assert_contract_status_change_allowed(contract, data)  # type: ignore[arg-type]
    assert status_change.calls == [((user, contract, data), {})]


async def test_user_policy_counts_order_amounts_once_per_client(monkeypatch) -> None:
    """Handler ekranu liczył kwoty raz — przed zapisem — i tym samym wynikiem
    redagował odpowiedź. Polityka pamięta wynik, więc wrapper trasy dostaje
    tę samą wartość bez drugiego zapytania."""
    user, db = _user(), object()
    policy = UserWritePolicy(user, db)  # type: ignore[arg-type]
    amounts = _OrderAmounts(can_read=True, can_write=False)
    computed = _AsyncSpy(amounts)
    gate = _Spy()
    monkeypatch.setattr(client_orders, "_order_amounts", computed)
    monkeypatch.setattr(client_orders, "_assert_order_finance_write_allowed", gate)

    await policy.assert_order_amounts_writable(5, {"rate_client"})
    assert await policy.order_amounts(5) is amounts
    assert computed.calls == [((db, user, 5), {})]
    assert gate.calls == [((user, {"rate_client"}), {"can_finance": False})]


def test_user_policy_author_is_the_user() -> None:
    user = _user()
    policy = UserWritePolicy(user, object())  # type: ignore[arg-type]
    assert policy.actor_id == 41
    assert policy.actor is user
    # Ładunek zdarzeń zamówienia z ekranu zostaje taki, jak był.
    assert policy.event_actor() == {}


# ── IntegrationWritePolicy: scope'y, nie role ────────────────────────────────


@pytest.fixture
def no_person_gates(monkeypatch):
    """Każda bramka osoby wywołana przez politykę konta = błąd testu."""
    monkeypatch.setattr(client_order_groups, "_require_order_lifecycle", _refuse)
    monkeypatch.setattr(
        client_order_groups, "_assert_line_finance_write_allowed", _refuse
    )
    monkeypatch.setattr(client_orders, "_order_amounts", _refuse)
    monkeypatch.setattr(client_orders, "_require_order_file_read", _refuse)
    monkeypatch.setattr(contracts, "_ensure_delivery_lead_contract_visible", _refuse)
    monkeypatch.setattr(contracts, "_assert_contract_finance_write_allowed", _refuse)

    def _no_permission_lookup(*_args, **_kwargs):
        raise AssertionError("konto serwisowe nie ma uprawnień osoby")

    monkeypatch.setattr(policy_module, "has_permission", _no_permission_lookup)


def _denied(exc: pytest.ExceptionInfo[HTTPException]) -> dict:
    assert exc.value.status_code == 403
    assert exc.value.detail["error"] == "insufficient_scope"
    return exc.value.detail


async def test_integration_lifecycle_checks_the_client_without_a_portfolio(
    monkeypatch, no_person_gates
) -> None:
    db = object()
    seen = _AsyncSpy()
    monkeypatch.setattr(client_order_groups, "_assert_client", seen)
    policy = IntegrationWritePolicy(_principal("orders:write"), db)  # type: ignore[arg-type]
    await policy.require_order_lifecycle(5, for_write=True)
    assert seen.calls == [((db, 5), {"for_write": True})]

    read_only = IntegrationWritePolicy(_principal("orders:read"), db)  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc:
        await read_only.require_order_lifecycle(5)
    assert _denied(exc)["missing"] == ["orders:write"]
    with pytest.raises(HTTPException) as exc:
        await read_only.require_order_file(5)
    assert _denied(exc)["missing"] == ["orders:write"]


async def test_integration_amounts_need_amounts_write(no_person_gates) -> None:
    orders_only = IntegrationWritePolicy(_principal("orders:write"), object())  # type: ignore[arg-type]
    # Pola operacyjne przechodzą bez kwot.
    await orders_only.assert_order_amounts_writable(5, {"end_date", "notes"})
    await orders_only.assert_line_amounts_writable(5, set())
    await orders_only.assert_contract_amounts_writable({"end_date"}, client_id=5)

    with pytest.raises(HTTPException) as exc:
        await orders_only.assert_order_amounts_writable(
            5, {"notes", "rate_client", "rate_candidate_currency"}
        )
    detail = _denied(exc)
    assert detail["missing"] == ["amounts:write"]
    assert detail["fields"] == ["rate_candidate_currency", "rate_client"]
    with pytest.raises(HTTPException) as exc:
        await orders_only.assert_line_amounts_writable(
            5, {"rate_cost", "md_budget_total"}
        )
    assert _denied(exc)["fields"] == ["md_budget_total", "rate_cost"]
    with pytest.raises(HTTPException) as exc:
        await orders_only.assert_contract_amounts_writable({"rate_client"}, client_id=5)
    assert _denied(exc)["fields"] == ["rate_client"]

    amounts = IntegrationWritePolicy(
        _principal("orders:write", "amounts:write"),
        object(),  # type: ignore[arg-type]
    )
    await amounts.assert_order_amounts_writable(5, {"rate_client"})
    await amounts.assert_line_amounts_writable(5, {"rate_cost", "budget_amount"})


async def test_integration_contract_writes_need_contracts_write(
    no_person_gates,
) -> None:
    from app.core.scheduling import business_today
    from app.models.contract import ContractStatus
    from datetime import timedelta

    today = business_today()
    contract = SimpleNamespace(
        client_id=5, status=ContractStatus.active, end_date=today + timedelta(days=90)
    )
    later = ContractUpdate(end_date=today + timedelta(days=120))
    ends_it = ContractUpdate(end_date=today - timedelta(days=1))

    writer = IntegrationWritePolicy(_principal("contracts:write"), object())  # type: ignore[arg-type]
    await writer.assert_contract_visible(contract)  # type: ignore[arg-type]
    # Termin w przyszłości = zwykła edycja (contracts:write wystarcza).
    writer.assert_contract_status_change_allowed(contract, later)  # type: ignore[arg-type]
    assert writer.can_edit_contracts() is True
    assert writer.can_edit_orders() is False
    # Data wsteczna kończy trwającą umowę = zmiana statusu (contracts:status),
    # jak uprawnienie ludzi „Status kontraktu”.
    with pytest.raises(HTTPException) as exc:
        writer.assert_contract_status_change_allowed(contract, ends_it)  # type: ignore[arg-type]
    assert _denied(exc)["missing"] == ["contracts:status"]
    both = IntegrationWritePolicy(
        _principal("contracts:write", "contracts:status"),
        object(),  # type: ignore[arg-type]
    )
    both.assert_contract_status_change_allowed(contract, ends_it)  # type: ignore[arg-type]

    reader = IntegrationWritePolicy(_principal("contracts:read"), object())  # type: ignore[arg-type]
    with pytest.raises(HTTPException) as exc:
        await reader.assert_contract_visible(contract)  # type: ignore[arg-type]
    assert _denied(exc)["missing"] == ["contracts:write"]


def test_integration_author_is_the_service_account() -> None:
    policy = IntegrationWritePolicy(_principal("orders:write"), object())  # type: ignore[arg-type]
    assert policy.actor_id is None
    assert isinstance(policy.actor, IntegrationActor)
    assert policy.actor.id is None
    assert policy.actor.service_account_id == 7
    assert policy.event_actor() == {"actor": "Integracja: Rozliczenia"}


def test_write_scopes_imply_their_reads() -> None:
    effective = implied_scopes(
        frozenset({"orders:write", "contracts:write", "amounts:write"})
    )
    assert {"orders:read", "contracts:read", "amounts:read"} <= effective
    assert ServiceScope.amounts_write.value in effective


# ── Kto buduje którą politykę ───────────────────────────────────────────────

_SCREEN_ROUTES = {
    "api/client_order_groups.py": {
        "close_order_group": "apply_group_close",
        "cancel_order_group": "apply_group_cancel",
        "extend_order_group": "apply_group_extend",
    },
    "api/client_orders.py": {
        "update_order": "apply_order_update",
        "close_order": "apply_order_close",
        "replace_order_po": "apply_order_file",
    },
    "api/contracts.py": {
        "update_contract": "apply_contract_update",
        "update_contract_status": "apply_contract_status",
    },
}


def _functions(rel: str) -> dict[str, ast.AsyncFunctionDef]:
    tree = ast.parse((_APP / rel).read_text(encoding="utf-8"))
    return {n.name: n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef)}


def _called_names(fn: ast.AST) -> set[str]:
    return {
        node.func.id
        for node in ast.walk(fn)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }


@pytest.mark.parametrize("rel", sorted(_SCREEN_ROUTES))
def test_screen_routes_delegate_with_the_user_policy(rel: str) -> None:
    functions = _functions(rel)
    for route, body in _SCREEN_ROUTES[rel].items():
        called = _called_names(functions[route])
        assert body in called, f"{rel}:{route} nie woła {body}"
        assert "UserWritePolicy" in called, f"{rel}:{route} bez polityki osoby"
        assert "IntegrationWritePolicy" not in called
        # Ciało nie zna użytkownika — tylko politykę.
        args = {
            a.arg for a in functions[body].args.args + functions[body].args.kwonlyargs
        }
        assert "policy" in args and not args & {"user", "current_user"}, body


def test_v1_writes_never_build_the_user_policy() -> None:
    for path in sorted((_APP / "api" / "integrations_v1").glob("*.py")):
        names = {
            node.id
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8")))
            if isinstance(node, ast.Name)
        }
        assert "UserWritePolicy" not in names, path.name
        assert "CurrentUser" not in names, path.name


# ── Wejście v1: tylko wymienione pola ───────────────────────────────────────


def test_v1_inputs_reject_fields_outside_the_contract() -> None:
    from pydantic import ValidationError

    from app.api.integrations_v1.contract_writes import ContractPatchIn
    from app.api.integrations_v1.order_writes import ExtendLineIn, OrderPatchIn

    with pytest.raises(ValidationError):
        OrderPatchIn.model_validate({"title": "nowy numer"})
    with pytest.raises(ValidationError):
        OrderPatchIn.model_validate({"rate_unit": "daily"})
    assert OrderPatchIn.model_validate({"end_date": None}).model_fields_set == {
        "end_date"
    }
    with pytest.raises(ValidationError):
        ContractPatchIn.model_validate({})
    with pytest.raises(ValidationError):
        ContractPatchIn.model_validate({"end_date": None, "rate_client": "1"})
    # Osoba przedłużenia tylko z kontraktem — API nie zakłada szkiców umów.
    with pytest.raises(ValidationError):
        ExtendLineIn.model_validate(
            {
                "candidate_id": 1,
                "rate_cost": "1",
                "rate_revenue": "2",
                "start_date": "2043-01-01",
            }
        )


def test_screen_validators_surface_as_v1_422() -> None:
    from app.api.integrations_v1.order_writes import _screen_model
    from app.schemas.client_order_group import OrderGroupExtend

    with pytest.raises(HTTPException) as exc:
        _screen_model(
            OrderGroupExtend,
            {
                "order_number": "MD/1",
                "start_date": date(2043, 1, 1),
                "lines": [
                    {
                        "contract_id": 1,
                        "rate_cost": "1",
                        "rate_revenue": "2",
                        "input_mode": "md",
                        "start_date": date(2043, 1, 1),
                    }
                ],
            },
        )
    assert exc.value.status_code == 422
    assert exc.value.detail["error"] == "validation_error"
    assert exc.value.detail["errors"]
