from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.section_access import (
    ProductSection,
    SectionAccess,
    require_section_access,
    require_section_access_any,
    require_section_access_any_read,
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


def _request(method: str, path: str = "/api/clients", route=None) -> Request:
    scope = {
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
    if route is not None:
        scope["route"] = route
    return Request(scope)


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
        client_inactive_cleanup,
        client_knowledge,
        client_materials,
        client_md_imports,
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
        client_inactive_cleanup.router,
        client_knowledge.router,
        client_materials.router,
        client_md_imports.router,
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

    # Od 0409 Delivery wynika z uprawnień: TCM zmienia status kontraktu, więc
    # ma w sekcji zapis (na produkcji miał go w panelu od 03.09.2026).
    assert (
        section_access_for_roles(
            [UserRole.talent_community_manager], ProductSection.delivery
        )
        is SectionAccess.write
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
    assert (
        section_access_for_roles([UserRole.finance], ProductSection.finance)
        is SectionAccess.write
    )


@pytest.mark.asyncio
async def test_delivery_dependency_is_read_only_with_view_permission_alone() -> None:
    """Sam podgląd Delivery czyta, ale nie zapisuje — także statusu kontraktu."""

    dependency = require_section_access(ProductSection.delivery)
    reader = _user(UserRole.recruiter)
    reader.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    reader.effective_section_access[ProductSection.delivery.value] = "read"

    assert await dependency(_request("GET"), reader) is reader
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("POST"), reader)
    assert getattr(exc_info.value, "status_code", None) == 403
    assert exc_info.value.detail["code"] == "section_access_denied"
    with pytest.raises(HTTPException):
        await dependency(_request("PATCH", "/api/contracts/42/status"), reader)


@pytest.mark.asyncio
async def test_delivery_dependency_lets_talent_community_manager_write() -> None:
    """TCM ma uprawnienie statusu, więc bramka sekcji przepuszcza zapis.

    O tym, KTÓRY zapis wolno wykonać, decyduje bramka uprawnienia na trasie.
    """

    dependency = require_section_access(ProductSection.delivery)
    tcm = _user(UserRole.talent_community_manager)

    assert await dependency(_request("GET"), tcm) is tcm
    assert await dependency(_request("PATCH", "/api/contracts/42/status"), tcm) is tcm


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "delivery,allowed", [("none", False), ("read", False), ("write", True)]
)
async def test_tcm_status_command_honours_a_revoked_delivery_section(
    delivery, allowed
) -> None:
    """Zmiana statusu wymaga zapisu w Delivery — także u TCM.

    Do 0409 TCM miał wyjątek w bramce sekcji (status przy samym odczycie).
    Status jest teraz uprawnieniem, z którego wynika zapis w sekcji, więc
    wyjątek zniknął: konto z samym odczytem (np. ograniczone starym wyjątkiem
    osoby) statusu nie zmieni.
    """
    tcm = _user(UserRole.talent_community_manager)
    tcm.effective_section_access = {section.value: "none" for section in ProductSection}
    tcm.effective_section_access[ProductSection.delivery.value] = delivery
    dependency = require_section_access(ProductSection.delivery)
    request = _request("PATCH", "/api/contracts/42/status")
    if allowed:
        assert await dependency(request, tcm) is tcm
    else:
        with pytest.raises(HTTPException) as exc_info:
            await dependency(request, tcm)
        assert exc_info.value.status_code == 403
        assert exc_info.value.detail["code"] == "section_access_denied"
        assert exc_info.value.detail["granted"] == delivery


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
        is SectionAccess.write
    )
    assert (
        section_access_for_roles(
            [UserRole.recruiter, UserRole.talent_community_manager],
            ProductSection.finance,
        )
        is SectionAccess.none
    )


def test_delivery_and_finance_come_from_permissions_not_stored_rows() -> None:
    user = _user(UserRole.recruiter, UserRole.talent_community_manager)
    role_rows = [
        SimpleNamespace(role="recruiter", section="delivery", access="none"),
        SimpleNamespace(
            role="talent_community_manager", section="delivery", access="write"
        ),
        SimpleNamespace(role="recruiter", section="pipeline", access="write"),
    ]
    # Zapisany wiersz sekcji zostaje w bazie, ale nie nadaje już dostępu.
    assert (
        base_policy_from_rows(user.get_all_roles(), role_rows)[ProductSection.delivery]
        is SectionAccess.write
    )
    without_permissions = effective_policy_from_rows(user, role_rows, [])
    assert without_permissions[ProductSection.delivery] is SectionAccess.none
    assert without_permissions[ProductSection.finance] is SectionAccess.none
    assert without_permissions[ProductSection.pipeline] is SectionAccess.write

    view_only = effective_policy_from_rows(
        user, role_rows, [], permissions=["delivery_view"]
    )
    assert view_only[ProductSection.delivery] is SectionAccess.read

    editor = effective_policy_from_rows(
        user, role_rows, [], permissions=["delivery_view", "contract_status"]
    )
    assert editor[ProductSection.delivery] is SectionAccess.write
    assert editor[ProductSection.finance] is SectionAccess.none

    finance = effective_policy_from_rows(
        user,
        role_rows,
        [],
        permissions=["delivery_view", "amounts_view", "finance_module"],
    )
    assert finance[ProductSection.delivery] is SectionAccess.read
    assert finance[ProductSection.finance] is SectionAccess.write


def test_legacy_user_override_only_restricts_a_derived_section() -> None:
    """Stary wyjątek osoby dla Delivery/Finansów ogranicza, nigdy nie podnosi."""

    user = _user(UserRole.talent_community_manager)
    permissions = ["delivery_view", "contract_status"]
    override_rows = [
        SimpleNamespace(user_id=user.id, section="delivery", access="write")
    ]
    assert (
        effective_policy_from_rows(user, [], override_rows)[ProductSection.delivery]
        is SectionAccess.none
    )

    override_rows[0].access = "read"
    assert (
        effective_policy_from_rows(user, [], override_rows, permissions=permissions)[
            ProductSection.delivery
        ]
        is SectionAccess.read
    )

    override_rows[0].access = "none"
    assert (
        effective_policy_from_rows(user, [], override_rows, permissions=permissions)[
            ProductSection.delivery
        ]
        is SectionAccess.none
    )


def test_user_override_still_replaces_a_stored_section() -> None:
    user = _user(UserRole.recruiter)
    role_rows = [SimpleNamespace(role="recruiter", section="insights", access="read")]
    override_rows = [
        SimpleNamespace(user_id=user.id, section="insights", access="write")
    ]
    assert (
        effective_policy_from_rows(user, role_rows, override_rows)[
            ProductSection.insights
        ]
        is SectionAccess.write
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
        pipeline,
        skills_admin,
        reports,
        talent_radar,
        talent_pools,
    )

    grouped = {
        ProductSection.sourcing: (
            candidates.router,
            talent_pools.router,
            talent_radar.router,
            skills_admin.router,
        ),
        ProductSection.pipeline: (jobs.router, pipeline.router),
        ProductSection.insights: (
            analytics_v1.router,
            hiring_managers_analytics.router,
            insights_board.router,
            insights_recruitment.router,
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


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "sourcing,pipeline,allowed",
    [(0, 0, False), (1, 0, True), (0, 1, True), (0, 2, True)],
)
async def test_shared_search_requires_read_in_at_least_one_section(
    monkeypatch, sourcing, pipeline, allowed
):
    import app.api.section_access as access

    user = SimpleNamespace(id=1)
    levels = {
        ProductSection.sourcing: SectionAccess(sourcing),
        ProductSection.pipeline: SectionAccess(pipeline),
    }
    monkeypatch.setattr(
        access, "section_access_for_user", lambda _user, section: levels[section]
    )
    guard = require_section_access_any_read(
        ProductSection.sourcing, ProductSection.pipeline
    )
    request = _request("POST", "/api/search/candidates")
    if allowed:
        assert await guard(request, user) is user
    else:
        with pytest.raises(HTTPException) as error:
            await guard(request, user)
        assert error.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "path,method,section,signature,allowed",
    [
        (
            "/api/b2b-generator/generated/123/confirm-fully-signed",
            "POST",
            "read",
            "manage",
            True,
        ),
        (
            "/api/b2b-generator/generated/123/confirm-fully-signed",
            "POST",
            "read",
            "none",
            False,
        ),
        (
            "/api/b2b-generator/generated/123/confirm-fully-signed",
            "POST",
            "none",
            "manage",
            False,
        ),
        ("/api/b2b-generator/generated/123", "PATCH", "read", "manage", False),
        ("/api/b2b-generator/generated/123", "DELETE", "read", "manage", False),
        ("/api/b2b-generator/generate", "POST", "read", "manage", False),
        (
            "/api/b2b-generator/generated/123/confirm-fully-signed/extra",
            "POST",
            "read",
            "manage",
            False,
        ),
    ],
)
async def test_signature_command_is_narrowly_configurable(
    path, method, section, signature, allowed
):
    user = _user(UserRole.talent_community_manager)
    user.effective_section_access = {"sourcing": section}
    user.effective_action_access = {
        "b2b_contract_generator": "view",
        "b2b_signature_confirmation": signature,
    }
    check = require_section_access(ProductSection.sourcing)
    if allowed:
        assert await check(_request(method, path), user) is user
    else:
        with pytest.raises(HTTPException) as exc:
            await check(_request(method, path), user)
        assert exc.value.status_code == 403


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,delivery,pipeline,allowed",
    [
        ("GET", 0, 0, False),
        ("GET", 1, 0, True),
        ("GET", 0, 1, True),
        ("POST", 1, 1, False),
        ("POST", 2, 0, True),
        ("POST", 0, 2, True),
        ("DELETE", 1, 2, True),
    ],
)
async def test_any_section_guard_derives_level_from_method(
    monkeypatch, method, delivery, pipeline, allowed
):
    """F02: przypisania DL↔klient edytuje Delivery Lead (Delivery) i Head of
    Recruitment (bez Delivery). Zapis wymaga zapisu w KTÓREJKOLWIEK sekcji,
    a nie samego odczytu — inaczej „dowolna z sekcji" otwierałaby mutacje."""
    import app.api.section_access as access

    user = SimpleNamespace(id=1)
    levels = {
        ProductSection.delivery: SectionAccess(delivery),
        ProductSection.pipeline: SectionAccess(pipeline),
    }
    monkeypatch.setattr(
        access, "section_access_for_user", lambda _user, section: levels[section]
    )
    guard = require_section_access_any(ProductSection.delivery, ProductSection.pipeline)
    request = _request(method, "/api/team-structure/dl-clients")
    if allowed:
        assert await guard(request, user) is user
    else:
        with pytest.raises(HTTPException) as error:
            await guard(request, user)
        assert error.value.status_code == 403
        assert error.value.detail["any_section"] == ["delivery", "pipeline"]


def test_any_section_guard_requires_at_least_one_section() -> None:
    with pytest.raises(ValueError):
        require_section_access_any()


# ── Odmowa sekcji Delivery/Finanse nazywa brakujące uprawnienie ──────────────
#
# Bramka sekcji biegnie przed bramką uprawnienia trasy. Bez nazwy osoba bez
# zapisu w Delivery dostawałaby ogólne „brak dostępu do sekcji” zamiast
# pozycji, o którą ma poprosić administratora.


def _snapshot_user(*, delivery: str, finance: str = "none", permissions=()):
    """Konto z kompletem obu migawek, jak po uwierzytelnieniu żądania."""

    from app.services.action_permissions import ProductAction

    user = _user(UserRole.recruiter)
    user.effective_section_access = {
        section.value: "none" for section in ProductSection
    }
    user.effective_section_access["delivery"] = delivery
    user.effective_section_access["finance"] = finance
    user.effective_action_access = {action.value: "none" for action in ProductAction}
    for key in permissions:
        user.effective_action_access[key] = "manage"
    return user


def _route_requiring(*aliases):
    """Trasa z prawdziwym okablowaniem FastAPI, która deklaruje uprawnienia."""

    from fastapi import APIRouter

    router = APIRouter()
    annotations = {f"gate_{index}": alias for index, alias in enumerate(aliases)}

    async def _endpoint(**_gates):
        return None

    _endpoint.__annotations__ = annotations
    import inspect

    _endpoint.__signature__ = inspect.Signature(
        [
            inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=alias)
            for name, alias in annotations.items()
        ]
    )
    router.add_api_route("/x", _endpoint, methods=["POST"])
    return router.routes[-1]


@pytest.mark.asyncio
async def test_delivery_read_denial_names_the_view_permission() -> None:
    dependency = require_section_access(ProductSection.delivery)
    outsider = _snapshot_user(delivery="none")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("GET"), outsider)

    assert exc_info.value.status_code == 403
    detail = exc_info.value.detail
    assert detail["code"] == "permission_denied"
    assert detail["permission"] == "delivery_view"
    assert "Klienci, kontrakty i zamówienia: podgląd" in detail["message"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "POST"])
async def test_finance_section_denial_names_the_finance_module(method) -> None:
    dependency = require_section_access(ProductSection.finance)
    outsider = _snapshot_user(delivery="write", permissions=("delivery_view",))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request(method, "/api/finance/order-changes"), outsider)

    assert exc_info.value.detail["code"] == "permission_denied"
    assert exc_info.value.detail["permission"] == "finance_module"


@pytest.mark.asyncio
async def test_delivery_write_denial_names_the_permission_the_route_declares() -> None:
    from app.api.permission_access import (
        ClientContractsEditUser,
        ContractsOrdersEditUser,
        ContractsOrdersOrAmountsEditUser,
    )

    dependency = require_section_access(ProductSection.delivery)
    reader = _snapshot_user(delivery="read", permissions=("delivery_view",))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request("POST", route=_route_requiring(ContractsOrdersEditUser)), reader
        )
    assert exc_info.value.detail["code"] == "permission_denied"
    assert exc_info.value.detail["permissions"] == ["contracts_orders_edit"]

    # Trasa mieszana: wystarczy jedno z dwóch — odmowa wymienia oba.
    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request("PATCH", route=_route_requiring(ContractsOrdersOrAmountsEditUser)),
            reader,
        )
    assert exc_info.value.detail["permissions"] == [
        "contracts_orders_edit",
        "amounts_edit",
    ]
    assert " albo " in exc_info.value.detail["message"]

    # Bramka z zakresem klienta deklaruje to samo uprawnienie.
    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request("POST", route=_route_requiring(ClientContractsEditUser)), reader
        )
    assert exc_info.value.detail["permissions"] == ["contracts_orders_edit"]


@pytest.mark.asyncio
async def test_delivery_write_denial_without_a_declared_permission_stays_generic() -> (
    None
):
    """Trasa z bramką roli albo regułą w środku handlera: nie zgadujemy nazwy."""

    dependency = require_section_access(ProductSection.delivery)
    reader = _snapshot_user(delivery="read", permissions=("delivery_view",))

    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("POST"), reader)

    detail = exc_info.value.detail
    assert detail["code"] == "section_access_denied"
    assert detail["required"] == "write"
    assert detail["granted"] == "read"
    assert "Poproś administratora" in detail["message"]


@pytest.mark.asyncio
async def test_denial_never_names_a_permission_the_account_already_has() -> None:
    """Stary wyjątek osoby ogranicza sekcję mimo posiadanego uprawnienia."""

    from app.api.permission_access import ContractsOrdersEditUser, DeliveryViewUser

    dependency = require_section_access(ProductSection.delivery)
    capped = _snapshot_user(
        delivery="read", permissions=("delivery_view", "contracts_orders_edit")
    )
    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request("POST", route=_route_requiring(ContractsOrdersEditUser)), capped
        )
    assert exc_info.value.detail["code"] == "section_access_denied"

    # POST będący odczytem w sensie uprawnienia (np. eksport): trasa wymaga
    # samego podglądu, który konto ma — brakuje zapisu w sekcji, nie podglądu.
    reader = _snapshot_user(delivery="read", permissions=("delivery_view",))
    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request("POST", route=_route_requiring(DeliveryViewUser)), reader
        )
    assert exc_info.value.detail["code"] == "section_access_denied"

    hidden = _snapshot_user(delivery="none", permissions=("delivery_view",))
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("GET"), hidden)
    assert exc_info.value.detail["code"] == "section_access_denied"


@pytest.mark.asyncio
async def test_shared_section_guard_names_only_a_declared_permission() -> None:
    from app.api.permission_access import ClientsEditUser

    guard = require_section_access_any(ProductSection.delivery, ProductSection.pipeline)
    outsider = _snapshot_user(delivery="none")

    with pytest.raises(HTTPException) as exc_info:
        await guard(_request("POST", route=_route_requiring(ClientsEditUser)), outsider)
    assert exc_info.value.detail["code"] == "permission_denied"
    assert exc_info.value.detail["permission"] == "clients_edit"

    # Bez deklaracji dostęp mógłby wynikać z drugiej sekcji — zostaje odmowa sekcji.
    with pytest.raises(HTTPException) as exc_info:
        await guard(_request("POST"), outsider)
    assert exc_info.value.detail["code"] == "section_access_denied"
    assert exc_info.value.detail["any_section"] == ["delivery", "pipeline"]


@pytest.mark.asyncio
async def test_sections_set_by_hand_keep_the_plain_section_denial() -> None:
    """Sourcing, Pipeline i Insights nie wynikają z uprawnień — bez zmian."""

    from app.api.permission_access import RecruitmentManageUser

    dependency = require_section_access(ProductSection.pipeline)
    outsider = _snapshot_user(delivery="none")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(
            _request(
                "POST", "/api/jobs", route=_route_requiring(RecruitmentManageUser)
            ),
            outsider,
        )

    assert exc_info.value.detail == {
        "code": "section_access_denied",
        "section": "pipeline",
        "required": "write",
        "granted": "none",
    }


@pytest.mark.asyncio
async def test_named_denial_reaches_the_client_through_real_routing() -> None:
    """Pełna ścieżka żądania: router z bramką sekcji + trasa z uprawnieniem.

    Testy wyżej podają trasę ręcznie; ten sprawdza, że FastAPI naprawdę
    wystawia ją bramce sekcji (``scope["route"]`` po dołączeniu routera).
    """

    from fastapi import APIRouter, FastAPI
    from httpx import ASGITransport, AsyncClient

    from app.api.deps import get_current_user, require_onboarded_user
    from app.api.permission_access import ContractsOrdersEditUser
    from app.api.section_access import DELIVERY_SECTION_DEPENDENCIES

    router = APIRouter(dependencies=DELIVERY_SECTION_DEPENDENCIES)

    @router.post("/contracts")
    async def _create(current_user: ContractsOrdersEditUser):
        return {"created_by": current_user.id}

    app = FastAPI()
    app.include_router(router, prefix="/api")
    account = {"user": _snapshot_user(delivery="read", permissions=("delivery_view",))}
    app.dependency_overrides[get_current_user] = lambda: account["user"]
    app.dependency_overrides[require_onboarded_user] = lambda: account["user"]

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        denied = await client.post("/api/contracts")
        account["user"] = _snapshot_user(
            delivery="write", permissions=("delivery_view", "contracts_orders_edit")
        )
        allowed = await client.post("/api/contracts")

    assert denied.status_code == 403
    assert denied.json()["detail"] == {
        "code": "permission_denied",
        "permission": "contracts_orders_edit",
        "label": "Kontrakty i zamówienia: tworzenie i edycja",
        "permissions": ["contracts_orders_edit"],
        "message": (
            "Brakuje Ci uprawnienia „Kontrakty i zamówienia: tworzenie i edycja”. "
            "Poproś administratora o dostęp."
        ),
    }
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_gate_that_needs_two_permissions_names_the_one_that_is_missing() -> None:
    """Narzędzia prawne wymagają edycji kontraktów ORAZ podglądu kwot."""

    from typing import Annotated

    from fastapi import Depends

    from app.api.contract_access import (
        require_contract_legal_access,
        require_contract_legal_read_access,
    )
    from app.models.user import User

    writer = Annotated[User, Depends(require_contract_legal_access)]
    reader = Annotated[User, Depends(require_contract_legal_read_access)]
    dependency = require_section_access(ProductSection.delivery)

    editor = _snapshot_user(
        delivery="read", permissions=("delivery_view", "contracts_orders_edit")
    )
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("POST", route=_route_requiring(writer)), editor)
    assert exc_info.value.detail["permissions"] == ["amounts_view"]

    outsider = _snapshot_user(delivery="none")
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("POST", route=_route_requiring(writer)), outsider)
    assert exc_info.value.detail["permissions"] == ["contracts_orders_edit"]
    with pytest.raises(HTTPException) as exc_info:
        await dependency(_request("GET", route=_route_requiring(reader)), outsider)
    assert exc_info.value.detail["permissions"] == ["amounts_view"]
