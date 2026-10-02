"""Focused command authorization without a database or production writes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.b2b_contract_generator import (
    _assert_signature_client_access,
    _require_signature_confirmation,
    _require_signature_job_scope,
)
from app.models.user import UserRole


def user_with_access(generator="view", signature="manage", role=UserRole.talent_community_manager):
    return SimpleNamespace(
        id=1,
        effective_action_access={
            "b2b_contract_generator": generator,
            "b2b_signature_confirmation": signature,
        },
        has_role=lambda required: required == role,
        has_any_role=lambda *required: role in required,
    )


def test_admin_granted_signature_does_not_require_generator_management():
    _require_signature_confirmation(user_with_access())
    _require_signature_confirmation(user_with_access(role=UserRole.recruiter))


@pytest.mark.parametrize("generator,signature", [("manage", "none"), ("none", "manage"), ("view", "view"), ("view", "generate")])
def test_signature_command_enforces_both_configured_gates(generator, signature):
    with pytest.raises(HTTPException) as exc:
        _require_signature_confirmation(user_with_access(generator, signature))
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_tcm_signature_scope_is_operational_but_dl_scope_is_preserved(monkeypatch):
    membership = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr("app.api.b2b_contract_generator.ensure_job_membership", membership)
    job = SimpleNamespace(id=42)
    await _require_signature_job_scope(None, user_with_access(), job)
    membership.assert_not_awaited()
    with pytest.raises(HTTPException):
        await _require_signature_job_scope(None, user_with_access(role=UserRole.delivery_lead), job)
    membership.assert_awaited_once()


@pytest.mark.asyncio
async def test_clientless_tcm_signature_reaches_link_validation(monkeypatch):
    legal_scope = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr("app.api.b2b_contract_generator.assert_contract_legal_client_access", legal_scope)
    await _assert_signature_client_access(None, user_with_access(), None)
    legal_scope.assert_not_awaited()
    # Zakres klienta zostaje wyłącznie przy koncie z rolą Delivery Leada.
    with pytest.raises(HTTPException):
        await _assert_signature_client_access(None, user_with_access(role=UserRole.delivery_lead), None)
    legal_scope.assert_awaited_once()


def user_with_roles(*roles):
    return SimpleNamespace(
        id=1,
        effective_action_access={
            "b2b_contract_generator": "manage",
            "b2b_signature_confirmation": "manage",
        },
        has_role=lambda required: required in roles,
        has_any_role=lambda *required: any(role in roles for role in required),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "extra_role", [UserRole.tac, UserRole.delivery_lead]
)
async def test_tcm_with_extra_scoped_role_still_confirms_org_wide(monkeypatch, extra_role):
    # 29.09.2026: konto TCM + TAC (osoba od Cpro) dostawało „Brak uprawnień do
    # potwierdzania podpisu dla tego klienta” — rola TAC włączała zakres klienta,
    # choć TCM potwierdza podpisy w całej organizacji (decyzja 10.09.2026).
    legal_scope = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr("app.api.b2b_contract_generator.assert_contract_legal_client_access", legal_scope)
    user = user_with_roles(UserRole.talent_community_manager, extra_role)
    await _assert_signature_client_access(None, user, 11)
    legal_scope.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("client_id", [11, None])
async def test_delivery_lead_confirms_only_inside_the_client_scope(monkeypatch, client_id):
    # Konto z rolą Delivery Leada (także z dodatkową rolą TAC) potwierdza podpis
    # u klientów z przypisania — zakres liczy `assert_contract_legal_client_access`.
    legal_scope = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr("app.api.b2b_contract_generator.assert_contract_legal_client_access", legal_scope)
    for user in (
        user_with_roles(UserRole.delivery_lead),
        user_with_roles(UserRole.delivery_lead, UserRole.tac),
    ):
        with pytest.raises(HTTPException) as exc:
            await _assert_signature_client_access(None, user, client_id)
        assert exc.value.status_code == 403
    assert legal_scope.await_count == 2
    assert legal_scope.await_args.args[2] == client_id
    assert legal_scope.await_args.kwargs == {"write": True, "purpose": "org"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "roles",
    [
        (UserRole.tac,),
        (UserRole.recruiter,),
        (UserRole.head_of_recruitment, UserRole.tac),
        (UserRole.finance,),
        (UserRole.admin,),
        (UserRole.admin, UserRole.delivery_lead),
    ],
)
@pytest.mark.parametrize("client_id", [11, None])
async def test_holder_outside_the_delivery_lead_portfolio_confirms_org_wide(monkeypatch, roles, client_id):
    # 02.10.2026: uprawnienie mówi CO, zakres mówi U KOGO. TAC nie ma już podpisu
    # domyślnie, a do tego dnia jego zakres klienta odmawiał zawsze (TAC nie ma
    # zapisu w Delivery) — rola, której administrator włączył uprawnienie na
    # ekranie, nie mogła z niego skorzystać. Konto bez portfela Delivery Leada
    # (także admin z dodatkową rolą DL) potwierdza u każdego klienta.
    legal_scope = AsyncMock(side_effect=HTTPException(status_code=403))
    monkeypatch.setattr("app.api.b2b_contract_generator.assert_contract_legal_client_access", legal_scope)
    await _assert_signature_client_access(None, user_with_roles(*roles), client_id)
    legal_scope.assert_not_awaited()
