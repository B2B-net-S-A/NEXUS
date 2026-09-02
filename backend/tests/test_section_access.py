from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.section_access import (
    ROLE_SECTION_ACCESS,
    ProductSection,
    SectionAccess,
    require_section_access,
    section_access_for_roles,
)
from app.models.user import UserRole


def _request(method: str) -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": "/api/clients",
            "raw_path": b"/api/clients",
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 443),
        }
    )


def _user(*roles: UserRole):
    return SimpleNamespace(get_all_roles=lambda: set(roles))


def test_section_matrix_is_closed_over_every_role_and_section() -> None:
    assert set(ROLE_SECTION_ACCESS) == set(UserRole)
    for policy in ROLE_SECTION_ACCESS.values():
        assert set(policy) == set(ProductSection)


def test_every_delivery_router_carries_the_central_section_guard() -> None:
    """A new handler in a Delivery router must inherit the coarse RBAC gate."""
    from app.api import (
        client_contract_amendments,
        client_directory,
        client_framework_contracts,
        client_knowledge,
        client_materials,
        client_order_groups,
        client_orders,
        clients,
        contractors,
        contract_templates,
        contracts,
        dl_alerts,
        my_clients,
        my_relationships,
        order_mail_queue,
    )

    delivery_routers = (
        client_contract_amendments.router,
        client_directory.router,
        client_framework_contracts.router,
        client_knowledge.router,
        client_materials.router,
        client_order_groups.router,
        client_orders.router,
        clients.router,
        contractors.router,
        contract_templates.router,
        contracts.router,
        dl_alerts.router,
        my_clients.router,
        my_relationships.router,
        order_mail_queue.router,
    )

    for router in delivery_routers:
        assert any(
            "require_section_access" in dependency.dependency.__qualname__
            for dependency in router.dependencies
        )


def test_mixed_required_documents_router_nests_the_delivery_guard() -> None:
    """Global templates stay shared; per-client documents are Delivery."""
    from inspect import signature

    from app.api.required_documents import (
        require_required_docs_read_access,
        require_required_docs_write_access,
    )
    from app.api.section_access import DeliverySectionUser

    for dependency in (
        require_required_docs_read_access,
        require_required_docs_write_access,
    ):
        assert signature(dependency).parameters["current_user"].annotation == (
            DeliverySectionUser
        )


def test_requested_delivery_and_finance_matrix() -> None:
    for role in (
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
        UserRole.head_of_recruitment,
    ):
        assert (
            section_access_for_roles([role], ProductSection.delivery)
            is SectionAccess.none
        )
        assert (
            section_access_for_roles([role], ProductSection.finance)
            is SectionAccess.none
        )

    assert (
        section_access_for_roles(
            [UserRole.talent_community_manager], ProductSection.delivery
        )
        is SectionAccess.read
    )
    assert (
        section_access_for_roles(
            [UserRole.talent_community_manager], ProductSection.finance
        )
        is SectionAccess.none
    )
    assert (
        section_access_for_roles([UserRole.delivery_lead], ProductSection.delivery)
        is SectionAccess.write
    )
    assert (
        section_access_for_roles([UserRole.delivery_lead], ProductSection.finance)
        is SectionAccess.none
    )


@pytest.mark.asyncio
async def test_delivery_dependency_is_read_only_for_talent_community_manager() -> None:
    dependency = require_section_access(ProductSection.delivery)
    tcm = _user(UserRole.talent_community_manager)

    assert await dependency(_request("GET"), tcm) is tcm
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("POST"), tcm)
    assert getattr(exc_info.value, "status_code", None) == 403
    assert exc_info.value.detail["code"] == "section_access_denied"


@pytest.mark.asyncio
async def test_delivery_dependency_rejects_recruitment_roles_before_handler() -> None:
    dependency = require_section_access(ProductSection.delivery)
    for role in (
        UserRole.sourcer,
        UserRole.recruiter,
        UserRole.tac,
        UserRole.head_of_recruitment,
    ):
        with pytest.raises(HTTPException) as exc_info:
            await dependency(_request("GET"), _user(role))
        assert getattr(exc_info.value, "status_code", None) == 403


def test_legacy_viewer_keeps_existing_non_delivery_read_surfaces() -> None:
    assert (
        section_access_for_roles([UserRole.user], ProductSection.pipeline)
        is SectionAccess.read
    )
    assert (
        section_access_for_roles([UserRole.user], ProductSection.insights)
        is SectionAccess.read
    )
    assert (
        section_access_for_roles([UserRole.user], ProductSection.delivery)
        is SectionAccess.none
    )


def test_multi_role_policy_is_union_without_finance_side_effect() -> None:
    assert (
        section_access_for_roles(
            [UserRole.recruiter, UserRole.talent_community_manager],
            ProductSection.delivery,
        )
        is SectionAccess.read
    )
    assert (
        section_access_for_roles(
            [UserRole.recruiter, UserRole.talent_community_manager],
            ProductSection.finance,
        )
        is SectionAccess.none
    )
