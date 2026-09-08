from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.section_access import (
    ProductSection,
    SectionAccess,
    require_section_access,
    section_access_for_user,
)
from app.models.user import UserRole
from app.services.section_permissions import (
    ROLE_SECTION_ACCESS,
    base_policy_from_rows,
    effective_policy_from_rows,
    section_access_for_roles,
)
from app.api.candidate_access import (
    CANDIDATE_READ_ROLES,
    CANDIDATE_WRITE_ROLES,
    require_candidate_finance_read,
    require_candidate_roles,
)


def _request(method: str, path: str = "/api/clients") -> Request:
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": method,
            "scheme": "https",
            "path": path,
            "raw_path": path.encode(),
            "query_string": b"",
            "headers": [],
            "client": ("127.0.0.1", 1),
            "server": ("test", 443),
        }
    )


def _user(*roles: UserRole):
    role_set = set(roles)
    return SimpleNamespace(
        id=17,
        get_all_roles=lambda: role_set,
        has_role=lambda role: role in role_set,
        has_any_role=lambda *required: bool(role_set.intersection(required)),
    )


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

    assert (
        await dependency(_request("PATCH", "/api/contracts/42/status"), tcm) is tcm
    )
    with pytest.raises(HTTPException):
        await dependency(_request("PATCH", "/api/contracts/42"), tcm)
    with pytest.raises(HTTPException):
        await dependency(_request("PATCH", "/api/contracts/not-a-number/status"), tcm)


@pytest.mark.asyncio
async def test_exact_read_only_post_uses_read_level_without_opening_sibling_mutation() -> (
    None
):
    dependency = require_section_access(ProductSection.pipeline)
    reader = _user(UserRole.recruiter)
    reader.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    reader.effective_section_access[ProductSection.pipeline.value] = "read"

    assert (
        await dependency(_request("POST", "/api/jobs/17/classify-cc"), reader) is reader
    )
    with pytest.raises(HTTPException):
        await dependency(_request("POST", "/api/jobs/17/cc-override"), reader)


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


def test_persisted_role_union_and_user_override_replace_the_base() -> None:
    user = _user(UserRole.recruiter, UserRole.talent_community_manager)
    role_rows = [
        SimpleNamespace(role="recruiter", section="delivery", access="none"),
        SimpleNamespace(
            role="talent_community_manager", section="delivery", access="read"
        ),
    ]
    assert (
        base_policy_from_rows(user.get_all_roles(), role_rows)[ProductSection.delivery]
        is SectionAccess.read
    )

    override_rows = [
        SimpleNamespace(user_id=user.id, section="delivery", access="write")
    ]
    assert (
        effective_policy_from_rows(user, role_rows, override_rows)[
            ProductSection.delivery
        ]
        is SectionAccess.write
    )

    override_rows[0].access = "none"
    assert (
        effective_policy_from_rows(user, role_rows, override_rows)[
            ProductSection.delivery
        ]
        is SectionAccess.none
    )


def test_missing_or_corrupt_persisted_rows_fail_closed() -> None:
    user = _user(UserRole.recruiter)
    assert all(
        access is SectionAccess.none
        for access in base_policy_from_rows(user.get_all_roles(), []).values()
    )
    corrupt = [SimpleNamespace(role="recruiter", section="finance", access="root")]
    assert (
        base_policy_from_rows(user.get_all_roles(), corrupt)[ProductSection.finance]
        is SectionAccess.none
    )


def test_resolved_request_snapshot_wins_over_static_role_matrix() -> None:
    user = _user(UserRole.recruiter)
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    user.effective_section_access[ProductSection.delivery.value] = "write"
    assert section_access_for_user(user, ProductSection.delivery) is SectionAccess.write
    assert section_access_for_user(user, ProductSection.sourcing) is SectionAccess.none


@pytest.mark.asyncio
async def test_user_override_can_grant_delivery_write_before_row_scope() -> None:
    dependency = require_section_access(ProductSection.delivery)
    user = _user(UserRole.recruiter)
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    user.effective_section_access[ProductSection.delivery.value] = "write"
    assert await dependency(_request("POST"), user) is user


@pytest.mark.asyncio
async def test_candidate_aliases_enforce_dynamic_read_and_write_levels() -> None:
    user = _user(UserRole.recruiter)
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    read_guard = require_candidate_roles(*CANDIDATE_READ_ROLES)
    write_guard = require_candidate_roles(
        *CANDIDATE_WRITE_ROLES,
        required_access=SectionAccess.write,
    )

    with pytest.raises(HTTPException):
        await read_guard(user)

    user.effective_section_access[ProductSection.sourcing.value] = "read"
    assert await read_guard(user) is user
    with pytest.raises(HTTPException):
        await write_guard(user)

    user.effective_section_access[ProductSection.sourcing.value] = "write"
    assert await write_guard(user) is user


@pytest.mark.asyncio
async def test_candidate_finance_read_honours_revoke_and_individual_grant() -> None:
    finance = _user(UserRole.finance)
    finance.effective_section_access = {
        section.value: "write" for section in ProductSection
    }
    finance.effective_section_access[ProductSection.finance.value] = "none"
    with pytest.raises(HTTPException):
        await require_candidate_finance_read(finance)

    recruiter = _user(UserRole.recruiter)
    recruiter.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    recruiter.effective_section_access[ProductSection.sourcing.value] = "read"
    recruiter.effective_section_access[ProductSection.finance.value] = "read"
    assert await require_candidate_finance_read(recruiter) is recruiter


def test_core_sourcing_pipeline_insights_and_finance_routers_have_section_guard() -> (
    None
):
    from app.api import (
        analytics_v1,
        candidates,
        finance,
        hiring_managers_analytics,
        insights_board,
        insights_recruitment,
        jobs,
        linkedin_metrics,
        pipeline,
        reports,
        talent_radar,
        talent_pools,
    )

    grouped = {
        ProductSection.sourcing: (
            candidates.router,
            talent_pools.router,
            talent_radar.router,
        ),
        ProductSection.pipeline: (jobs.router, pipeline.router),
        ProductSection.insights: (
            analytics_v1.router,
            hiring_managers_analytics.router,
            insights_board.router,
            insights_recruitment.router,
            linkedin_metrics.router,
            reports.router,
        ),
        ProductSection.finance: (finance.router,),
    }
    for routers in grouped.values():
        for router in routers:
            assert any(
                "require_section_access" in dependency.dependency.__qualname__
                for dependency in router.dependencies
            )
