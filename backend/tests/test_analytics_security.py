"""Focused unit coverage for analytics/DynaReporter R0 security guards."""

from __future__ import annotations

from dataclasses import dataclass, field

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.analytics.capabilities import AnalyticsCapability
from app.api.contractors import _require_contractor_access
from app.api.deps import (
    DynaReporterSection,
    _enforce_passive_viewer_scope,
    require_analytics_capabilities,
    require_dynareporter_access,
    require_dynareporter_section,
)
from app.core.config import settings
from app.models.user import UserRole
from app.services.infrareporter import get_infrareporter_kpis


@dataclass
class DummyUser:
    id: int = 1
    role: UserRole = UserRole.user
    roles: list[str] = field(default_factory=list)
    allowed_sections: list[str] = field(default_factory=list)

    def get_all_roles(self) -> set[UserRole]:
        values = {self.role}
        for role in self.roles:
            try:
                values.add(UserRole(role))
            except ValueError:
                pass
        return values

    def has_role(self, role: UserRole | str) -> bool:
        value = role.value if isinstance(role, UserRole) else role
        return value in {item.value for item in self.get_all_roles()}

    def has_any_role(self, *roles: UserRole) -> bool:
        return any(self.has_role(role) for role in roles)


def _request(method: str = "GET") -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/dynareporter/test",
            "headers": [],
        }
    )


def _path_request(path: str, method: str = "GET") -> Request:
    return Request(
        {"type": "http", "method": method, "path": path, "headers": []}
    )


@pytest.mark.asyncio
async def test_section_grant_never_expands_role_capability(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "admin_write")
    user = DummyUser(
        role=UserRole.user,
        allowed_sections=[DynaReporterSection.board.value],
    )
    guard = require_dynareporter_section(DynaReporterSection.board)

    with pytest.raises(HTTPException) as exc:
        await guard(request=_request(), current_user=user)

    assert exc.value.status_code == 403
    assert "view_finance" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_section_requires_explicit_legacy_grant(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "admin_write")
    dl = DummyUser(role=UserRole.delivery_lead, allowed_sections=[])
    guard = require_dynareporter_section(DynaReporterSection.board)

    with pytest.raises(HTTPException) as exc:
        await guard(request=_request(), current_user=dl)

    assert exc.value.status_code == 403
    assert "section not granted" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_matching_role_and_section_are_accepted(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "admin_write")
    dl = DummyUser(
        role=UserRole.delivery_lead,
        allowed_sections=[DynaReporterSection.board.value],
    )
    guard = require_dynareporter_section(DynaReporterSection.board)

    assert await guard(request=_request(), current_user=dl) is dl


@pytest.mark.asyncio
async def test_secondary_admin_preserves_admin_section_bypass(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "admin_write")
    hybrid = DummyUser(
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value, UserRole.admin.value],
        allowed_sections=[],
    )
    guard = require_dynareporter_section(DynaReporterSection.admin)

    assert await guard(request=_request(), current_user=hybrid) is hybrid


@pytest.mark.asyncio
async def test_read_only_mode_returns_410_for_legacy_write(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "read_only")
    admin = DummyUser(role=UserRole.admin)
    guard = require_dynareporter_section(DynaReporterSection.admin)

    with pytest.raises(HTTPException) as exc:
        await guard(request=_request("POST"), current_user=admin)

    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_off_mode_returns_410_for_read(monkeypatch) -> None:
    monkeypatch.setattr(settings, "DYNAREPORTER_MODE", "off")
    admin = DummyUser(role=UserRole.admin)

    with pytest.raises(HTTPException) as exc:
        await require_dynareporter_access(request=_request(), current_user=admin)

    assert exc.value.status_code == 410


@pytest.mark.asyncio
async def test_capability_guard_uses_secondary_roles() -> None:
    hybrid = DummyUser(
        role=UserRole.recruiter,
        roles=[UserRole.recruiter.value, UserRole.delivery_lead.value],
    )
    guard = require_analytics_capabilities(
        AnalyticsCapability.view_personal_recruitment_kpis,
        AnalyticsCapability.view_finance,
    )

    assert await guard(current_user=hybrid) is hybrid


def test_passive_viewer_cannot_access_contractor_pii_or_rates() -> None:
    with pytest.raises(HTTPException) as exc:
        _require_contractor_access(DummyUser(role=UserRole.user))
    assert exc.value.status_code == 403

    # A secondary operational role grants the normal scoped contractor view.
    hybrid = DummyUser(
        role=UserRole.user,
        roles=[UserRole.user.value, UserRole.recruiter.value],
    )
    _require_contractor_access(hybrid)


def test_passive_viewer_global_gate_allows_only_safe_aggregates() -> None:
    viewer = DummyUser(role=UserRole.user)
    _enforce_passive_viewer_scope(
        _path_request("/api/analytics/v1/overview"), viewer
    )
    _enforce_passive_viewer_scope(_path_request("/api/dashboard/stats"), viewer)

    for forbidden_path in (
        "/api/candidates",
        "/api/clients",
        "/api/activities/feed",
        "/api/competitions/current",
        "/api/analytics/v1/team/kpis",
    ):
        with pytest.raises(HTTPException) as exc:
            _enforce_passive_viewer_scope(_path_request(forbidden_path), viewer)
        assert exc.value.status_code == 403


def test_secondary_operational_role_is_not_restricted_by_viewer_gate() -> None:
    hybrid = DummyUser(
        role=UserRole.user,
        roles=[UserRole.user.value, UserRole.recruiter.value],
    )
    _enforce_passive_viewer_scope(_path_request("/api/candidates"), hybrid)


@pytest.mark.asyncio
async def test_infrareporter_is_disabled_without_vault_secret(monkeypatch) -> None:
    monkeypatch.setattr(settings, "INFRAREPORTER_API_KEY", "")
    assert await get_infrareporter_kpis() is None
