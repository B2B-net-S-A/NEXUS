"""Odmowa bramki rolowej mówi po polsku i nie ujawnia listy ról (UAT M02-B04)."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.api.deps import ROLE_DENIED_DETAIL, require_roles
from app.models.user import UserRole


@pytest.mark.asyncio
async def test_role_gate_denial_is_polish_and_hides_role_names():
    user = SimpleNamespace(
        id=1,
        has_role=lambda role: False,
        has_any_role=lambda *roles: False,
    )
    check = require_roles(UserRole.tac, UserRole.delivery_lead)
    with pytest.raises(HTTPException) as exc:
        await check(current_user=user)
    assert exc.value.status_code == 403
    assert exc.value.detail == ROLE_DENIED_DETAIL
    assert "tac" not in exc.value.detail
