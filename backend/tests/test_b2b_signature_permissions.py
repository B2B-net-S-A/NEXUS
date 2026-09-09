"""Focused command authorization without a database or production writes."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from app.api.b2b_contract_generator import (
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
