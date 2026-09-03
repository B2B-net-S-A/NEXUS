"""Regression tests for database-backed Finance section access.

The section grant controls financial data, while legal-document personas and
client scope remain independent boundaries.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.analytics.capabilities import AnalyticsCapability, capabilities_for
from app.api import client_order_groups, contract_access, contracts
from app.models.user import User, UserRole
from app.services.access_scope import ScopeKind, resolve_dashboard_scope
from app.services.section_permissions import ProductSection


def _user(role: UserRole, finance: str) -> User:
    user = User(
        id=41,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    user.effective_section_access[ProductSection.finance.value] = finance
    return user


def test_finance_section_is_the_ceiling_for_financial_capabilities() -> None:
    revoked = capabilities_for(_user(UserRole.finance, "none"))
    assert AnalyticsCapability.VIEW_FINANCE not in revoked
    assert AnalyticsCapability.MANAGE_FINANCE not in revoked

    read = capabilities_for(_user(UserRole.recruiter, "read"))
    assert AnalyticsCapability.VIEW_FINANCE in read
    assert AnalyticsCapability.MANAGE_FINANCE not in read

    write = capabilities_for(_user(UserRole.recruiter, "write"))
    assert AnalyticsCapability.VIEW_FINANCE in write
    assert AnalyticsCapability.MANAGE_FINANCE in write
    assert AnalyticsCapability.APPROVE_FINANCE not in write


def test_insights_revoke_removes_non_financial_analytics_capabilities() -> None:
    finance_only = _user(UserRole.finance, "read")
    caps = capabilities_for(finance_only)
    assert AnalyticsCapability.VIEW_FINANCE in caps
    assert AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES not in caps
    assert AnalyticsCapability.VIEW_TEAM_KPI not in caps

    recruiter = _user(UserRole.recruiter, "none")
    assert capabilities_for(recruiter) == frozenset()


@pytest.mark.asyncio
async def test_opaque_contract_documents_require_persona_and_finance_grant() -> None:
    finance_revoked = _user(UserRole.finance, "none")
    with pytest.raises(HTTPException) as exc:
        await contracts.require_contract_document_read_access(finance_revoked)
    assert exc.value.status_code == 403

    finance_reader = _user(UserRole.finance, "read")
    assert (
        await contracts.require_contract_document_read_access(finance_reader)
        is finance_reader
    )

    # A section exception grants financial data, not the separate legal persona.
    recruiter_reader = _user(UserRole.recruiter, "read")
    with pytest.raises(HTTPException) as exc:
        await contracts.require_contract_document_read_access(recruiter_reader)
    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_contract_template_legal_read_honours_finance_revoke(
    monkeypatch,
) -> None:
    async def no_client_assignments(*_args, **_kwargs):
        return frozenset()

    monkeypatch.setattr(
        contract_access,
        "resolve_client_team_client_ids",
        no_client_assignments,
    )

    with pytest.raises(HTTPException) as exc:
        await contract_access.require_contract_legal_read_access(
            _user(UserRole.finance, "none"),
            SimpleNamespace(),
        )
    assert exc.value.status_code == 403

    finance_reader = _user(UserRole.finance, "read")
    assert (
        await contract_access.require_contract_legal_read_access(
            finance_reader,
            SimpleNamespace(),
        )
        is finance_reader
    )


@pytest.mark.asyncio
async def test_order_pdf_guard_does_not_use_finance_role_as_a_shortcut(
    monkeypatch,
) -> None:
    async def client_exists(*_args, **_kwargs):
        return SimpleNamespace(id=7)

    async def no_legal_access(*_args, **_kwargs):
        return SimpleNamespace(can_view_legal_documents=False)

    monkeypatch.setattr(client_order_groups, "_assert_client", client_exists)
    monkeypatch.setattr(
        client_order_groups,
        "resolve_client_access",
        no_legal_access,
    )

    with pytest.raises(HTTPException):
        await client_order_groups._require_group_read(
            SimpleNamespace(),
            _user(UserRole.finance, "none"),
            7,
        )

    finance_reader = _user(UserRole.finance, "read")
    await client_order_groups._require_group_read(
        SimpleNamespace(),
        finance_reader,
        7,
    )

    # An individual grant still cannot bypass the client/legal record guard.
    with pytest.raises(HTTPException):
        await client_order_groups._require_group_read(
            SimpleNamespace(),
            _user(UserRole.recruiter, "read"),
            7,
        )


def test_finance_order_lifecycle_requires_write_access() -> None:
    assert not client_order_groups._has_order_lifecycle_role(
        _user(UserRole.finance, "none")
    )
    assert not client_order_groups._has_order_lifecycle_role(
        _user(UserRole.finance, "read")
    )
    assert client_order_groups._has_order_lifecycle_role(
        _user(UserRole.finance, "write")
    )


@pytest.mark.asyncio
async def test_individual_finance_grant_does_not_widen_dashboard_scope() -> None:
    user = _user(UserRole.recruiter, "write")
    scope = await resolve_dashboard_scope(user, SimpleNamespace())
    assert scope.kind is ScopeKind.self
    assert scope.user_id == user.id
