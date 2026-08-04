"""Authorization, scope and response-contract tests for Dashboard v2."""

from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI, HTTPException
from httpx import ASGITransport, AsyncClient

from app.api import dashboard_v2 as dashboard_api
from app.api.deps import get_current_user
from app.analytics.periods import resolve_period
from app.core.database import get_db
from app.models.user import User, UserRole
from app.schemas.dashboard_v2 import (
    AdminOpsDashboardResponse,
    DashboardScopePayload,
    DeliveryLeadDashboardResponse,
    FinanceDashboardResponse,
    HeadOfRecruitmentDashboardResponse,
    MyWorkDashboardResponse,
)
from app.services.dashboard_v2_sources import (
    ResolvedDashboardScope,
    _delivery_job_conditions,
    _delivery_milestone_job_actor_pairs,
    load_delivery_demands,
    narrow_to_self,
)
from app.services import dashboard_v2_sources
from app.services.dashboard_v2 import (
    build_admin_ops_dashboard,
    build_finance_dashboard,
    build_head_of_recruitment_dashboard,
    build_my_work_dashboard,
)


def _user(role: UserRole, *, user_id: int = 11) -> User:
    return User(
        id=user_id,
        email=f"{role.value}-{user_id}@example.com",
        name=f"Dashboard {role.value}",
        role=role,
        roles=[role.value],
        is_active=True,
        profile_completed=True,
    )


@pytest_asyncio.fixture
async def dashboard_client() -> AsyncIterator[tuple[AsyncClient, dict[str, User]]]:
    app = FastAPI()
    app.include_router(dashboard_api.router, prefix="/api/dashboard/v2")
    context = {"user": _user(UserRole.user)}

    async def _current_user() -> User:
        return context["user"]

    async def _db() -> AsyncIterator[object]:
        yield object()

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db] = _db

    async with AsyncClient(
        transport=ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://testserver",
    ) as client:
        yield client, context


async def _authorized_builder(*_args: Any, **_kwargs: Any) -> None:
    raise HTTPException(status_code=418, detail="authorized")


@pytest.mark.parametrize(
    ("path", "role", "builder"),
    [
        ("/admin-ops", UserRole.admin, "build_admin_ops_dashboard"),
        (
            "/delivery-lead",
            UserRole.delivery_lead,
            "build_delivery_lead_dashboard",
        ),
        (
            "/head-of-recruitment",
            UserRole.head_of_recruitment,
            "build_head_of_recruitment_dashboard",
        ),
        ("/my-work", UserRole.sourcer, "build_my_work_dashboard"),
        ("/my-work", UserRole.tac, "build_my_work_dashboard"),
        ("/my-work", UserRole.recruiter, "build_my_work_dashboard"),
        ("/finance", UserRole.finance, "build_finance_dashboard"),
        (
            "/finance?tab=executive",
            UserRole.finance,
            "build_finance_dashboard",
        ),
    ],
)
@pytest.mark.asyncio
async def test_role_is_authorized_for_its_dashboard(
    dashboard_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    role: UserRole,
    builder: str,
) -> None:
    client, context = dashboard_client
    context["user"] = _user(role)
    monkeypatch.setattr(dashboard_api, builder, _authorized_builder)

    response = await client.get(f"/api/dashboard/v2{path}")

    assert response.status_code == 418
    assert response.json()["detail"] == "authorized"


@pytest.mark.parametrize(
    ("path", "builder"),
    [
        ("/admin-ops", "build_admin_ops_dashboard"),
        ("/delivery-lead", "build_delivery_lead_dashboard"),
        ("/head-of-recruitment", "build_head_of_recruitment_dashboard"),
        ("/my-work", "build_my_work_dashboard"),
        ("/finance", "build_finance_dashboard"),
        ("/finance?tab=executive", "build_finance_dashboard"),
    ],
)
@pytest.mark.asyncio
async def test_admin_is_authorized_for_every_dashboard_preset(
    dashboard_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    builder: str,
) -> None:
    client, context = dashboard_client
    context["user"] = _user(UserRole.admin)
    monkeypatch.setattr(dashboard_api, builder, _authorized_builder)

    response = await client.get(f"/api/dashboard/v2{path}")

    assert response.status_code == 418


@pytest.mark.parametrize(
    "path",
    [
        "/admin-ops",
        "/delivery-lead",
        "/head-of-recruitment",
        "/my-work",
        "/finance",
        "/finance?tab=executive",
    ],
)
@pytest.mark.asyncio
async def test_legacy_viewer_is_denied_every_dashboard(
    dashboard_client: tuple[AsyncClient, dict[str, User]],
    path: str,
) -> None:
    client, context = dashboard_client
    context["user"] = _user(UserRole.user)

    response = await client.get(f"/api/dashboard/v2{path}")

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_executive_tab_requires_separate_capability(
    dashboard_client: tuple[AsyncClient, dict[str, User]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, context = dashboard_client
    context["user"] = _user(UserRole.finance)
    monkeypatch.setattr(
        dashboard_api,
        "user_has_capability",
        lambda _user, _cap: False,
    )
    monkeypatch.setattr(
        dashboard_api,
        "build_finance_dashboard",
        _authorized_builder,
    )

    response = await client.get("/api/dashboard/v2/finance?tab=executive")

    assert response.status_code == 403
    assert response.json()["detail"] == (
        "Requires analytics capability: view_executive"
    )


@pytest.mark.asyncio
async def test_finance_tab_is_a_closed_enum(
    dashboard_client: tuple[AsyncClient, dict[str, User]],
) -> None:
    client, context = dashboard_client
    context["user"] = _user(UserRole.finance)

    response = await client.get("/api/dashboard/v2/finance?tab=unknown")

    assert response.status_code == 422


def _property_names(schema: dict[str, Any]) -> set[str]:
    names: set[str] = set()

    def _walk(node: Any) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                names.update(properties)
            for value in node.values():
                _walk(value)
        elif isinstance(node, list):
            for value in node:
                _walk(value)

    _walk(schema)
    return names


def test_every_dashboard_response_has_common_metadata() -> None:
    for model in (
        AdminOpsDashboardResponse,
        DeliveryLeadDashboardResponse,
        HeadOfRecruitmentDashboardResponse,
        MyWorkDashboardResponse,
        FinanceDashboardResponse,
    ):
        assert {
            "schema_version",
            "generated_at",
            "scope",
            "data_quality",
            "data",
        } <= set(model.model_fields)
        assert model.model_config["extra"] == "forbid"


def test_delivery_contract_structurally_excludes_finance_fields() -> None:
    fields = _property_names(DeliveryLeadDashboardResponse.model_json_schema())

    assert fields.isdisjoint(
        {
            "amount",
            "currency",
            "invoice_id",
            "invoice_number",
            "margin",
            "margin_pct",
            "mrr",
            "rate",
            "revenue",
        }
    )


def test_finance_contract_structurally_excludes_candidate_pii() -> None:
    fields = _property_names(FinanceDashboardResponse.model_json_schema())

    assert fields.isdisjoint(
        {
            "candidate",
            "candidate_id",
            "candidate_name",
            "email",
            "first_name",
            "last_name",
            "phone",
        }
    )


def test_finance_contract_discriminates_operations_and_executive_tabs() -> None:
    data_schema = FinanceDashboardResponse.model_json_schema()["properties"]["data"]

    assert data_schema["discriminator"]["propertyName"] == "tab"
    assert set(data_schema["discriminator"]["mapping"]) == {
        "operations",
        "executive",
    }


def test_admin_my_work_scope_is_narrowed_to_current_user() -> None:
    admin = _user(UserRole.admin, user_id=42)
    organization_scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="organization",
            user_id=admin.id,
            client_ids=[1, 2],
            tac_user_ids=[3],
            operator_user_ids=[3, 4],
        ),
    )

    narrowed = narrow_to_self(admin, organization_scope)

    assert narrowed.payload == DashboardScopePayload(
        kind="self",
        user_id=42,
        client_ids=[],
        tac_user_ids=[42],
        operator_user_ids=[42],
    )


def test_non_admin_organization_scope_cannot_become_my_work() -> None:
    finance = _user(UserRole.finance)
    organization_scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="organization",
            user_id=finance.id,
        ),
    )

    with pytest.raises(HTTPException) as exc_info:
        narrow_to_self(finance, organization_scope)

    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "primary_role",
    [UserRole.delivery_lead, UserRole.head_of_recruitment],
)
def test_multi_role_operator_can_narrow_oversight_scope_to_my_work(
    primary_role: UserRole,
) -> None:
    operator = _user(primary_role, user_id=44)
    operator.roles = [primary_role.value, UserRole.tac.value]
    oversight_scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind=(
                "delivery_clients"
                if primary_role is UserRole.delivery_lead
                else "recruitment_org"
            ),
            user_id=operator.id,
            client_ids=[8, 9],
            tac_user_ids=[21, 22],
            operator_user_ids=[21, 22],
            client_tac_pairs=[
                {"client_id": 8, "tac_user_id": 21},
                {"client_id": 9, "tac_user_id": 22},
            ],
        ),
    )

    narrowed = narrow_to_self(operator, oversight_scope)

    assert narrowed.payload == DashboardScopePayload(
        kind="self",
        user_id=44,
        tac_user_ids=[44],
        operator_user_ids=[44],
    )


def test_delivery_scope_uses_exact_client_tac_pairs_not_cartesian_product() -> None:
    delivery_lead = _user(UserRole.delivery_lead, user_id=71)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="delivery_clients",
            user_id=delivery_lead.id,
            client_ids=[8, 9],
            tac_user_ids=[21, 22],
            operator_user_ids=[21, 22],
            client_tac_pairs=[
                {"client_id": 8, "tac_user_id": 21},
                {"client_id": 9, "tac_user_id": 22},
            ],
        ),
    )

    rendered = " ".join(
        str(condition.compile(compile_kwargs={"literal_binds": True}))
        for condition in _delivery_job_conditions(delivery_lead, scope)
    )

    assert "jobs.client_id" in rendered
    assert "jobs.tac_id" in rendered
    assert "(8, 21)" in rendered
    assert "(9, 22)" in rendered
    assert "(8, 22)" not in rendered
    assert "(9, 21)" not in rendered
    assert "jobs.delivery_lead_id" not in rendered


def test_delivery_scope_without_relationship_pairs_is_empty() -> None:
    delivery_lead = _user(UserRole.delivery_lead, user_id=71)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="delivery_clients",
            user_id=delivery_lead.id,
            client_ids=[8],
            tac_user_ids=[21],
            operator_user_ids=[21],
        ),
    )

    rendered = " ".join(
        str(condition.compile(compile_kwargs={"literal_binds": True}))
        for condition in _delivery_job_conditions(delivery_lead, scope)
    )

    assert "(-1, -1)" in rendered


def test_delivery_milestone_actor_scope_preserves_client_relationship() -> None:
    delivery_lead = _user(UserRole.delivery_lead, user_id=71)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="delivery_clients",
            user_id=delivery_lead.id,
            client_ids=[8, 9],
            tac_user_ids=[21, 22],
            operator_user_ids=[21, 22],
            client_tac_pairs=[
                {"client_id": 8, "tac_user_id": 21},
                {"client_id": 9, "tac_user_id": 22},
            ],
        ),
    )
    job_rows = [
        SimpleNamespace(id=101, client_id=8),
        SimpleNamespace(id=202, client_id=9),
    ]

    allowed = _delivery_milestone_job_actor_pairs(job_rows, scope)

    assert allowed == [(101, 21), (202, 22)]
    assert (101, 22) not in allowed
    assert (202, 21) not in allowed


@pytest.mark.asyncio
async def test_delivery_demands_query_uses_resolved_job_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ScalarRows:
        def all(self) -> list[object]:
            return [object()]

    class _Result:
        def scalars(self) -> _ScalarRows:
            return _ScalarRows()

    class _Database:
        statement: Any = None

        async def execute(self, statement: Any) -> _Result:
            self.statement = statement
            return _Result()

    async def _serialize(_db: object, _row: object) -> dict[str, Any]:
        return {"job": {"id": 81}}

    monkeypatch.setattr(
        dashboard_v2_sources.priority_work,
        "_serialize_demand",
        _serialize,
    )
    db = _Database()

    rows = await load_delivery_demands(
        _user(UserRole.delivery_lead),
        db,  # type: ignore[arg-type]
        {81, 82},
    )

    rendered = str(db.statement)
    assert rows == [{"job": {"id": 81}}]
    assert "recruitment_priority_demands.job_id IN" in rendered
    assert "jobs.delivery_lead_id" not in rendered


@pytest.mark.asyncio
async def test_disabled_cloudtalk_is_unavailable_not_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _user(UserRole.recruiter)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="self",
            user_id=operator.id,
            tac_user_ids=[operator.id],
            operator_user_ids=[operator.id],
        ),
    )

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _priority(*_args: Any) -> dict[str, Any]:
        return {"assignments": [], "carry_over": []}

    async def _kpis(*_args: Any) -> dict[str, Any]:
        return {
            "completed_calls": 0,
            "first_verifications": 0,
            "first_recommendations": 0,
            "first_placements": 0,
        }

    async def _contact_status(*_args: Any) -> dict[str, Any]:
        return {"enabled": False}

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_my_priority_work",
        _priority,
    )
    monkeypatch.setattr(dashboard_v2_sources, "load_user_kpis", _kpis)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_contact_feature_status",
        _contact_status,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "cloudtalk_calls_available",
        lambda: False,
    )

    response = await build_my_work_dashboard(
        operator,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
    )

    assert response.data.kpis.completed_calls.value is None
    assert response.data.kpis.completed_calls.quality == "unavailable"
    assert response.data_quality.sections["completed_calls"].status == "unavailable"


@pytest.mark.asyncio
async def test_failed_team_roster_never_becomes_zero_placements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader = _user(UserRole.head_of_recruitment)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="recruitment_org",
            user_id=leader.id,
            tac_user_ids=[],
            operator_user_ids=[],
        ),
    )
    kpis_called = False

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _failed_team(*_args: Any) -> dict[str, Any]:
        raise RuntimeError("priority source unavailable")

    async def _contact(*_args: Any) -> dict[str, Any]:
        return {"counters": {}}

    async def _kpis(*_args: Any) -> dict[str, Any]:
        nonlocal kpis_called
        kpis_called = True
        return {"first_placements": 0}

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_team_priority_work",
        _failed_team,
    )
    monkeypatch.setattr(dashboard_v2_sources, "load_contact_oversight", _contact)
    monkeypatch.setattr(dashboard_v2_sources, "load_user_kpis", _kpis)

    response = await build_head_of_recruitment_dashboard(
        leader,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
    )

    assert not kpis_called
    assert response.data.kpis.placements.value is None
    assert response.data.kpis.placements.quality == "unavailable"
    assert response.data_quality.sections["team_kpis"].status == "unavailable"


@pytest.mark.asyncio
async def test_malformed_team_roster_never_becomes_complete_zeroes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    leader = _user(UserRole.head_of_recruitment)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="recruitment_org",
            user_id=leader.id,
            tac_user_ids=[],
            operator_user_ids=[],
        ),
    )
    kpis_called = False

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _malformed_team(*_args: Any) -> dict[str, Any]:
        return {}

    async def _contact(*_args: Any) -> dict[str, Any]:
        return {"counters": {}}

    async def _kpis(*_args: Any) -> dict[str, Any]:
        nonlocal kpis_called
        kpis_called = True
        return {"first_placements": 0}

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_team_priority_work",
        _malformed_team,
    )
    monkeypatch.setattr(dashboard_v2_sources, "load_contact_oversight", _contact)
    monkeypatch.setattr(dashboard_v2_sources, "load_user_kpis", _kpis)

    response = await build_head_of_recruitment_dashboard(
        leader,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
    )

    assert not kpis_called
    assert response.data.kpis.priority_vacancies.value is None
    assert response.data.kpis.unassigned_work.value is None
    assert response.data.kpis.placements.value is None
    assert response.data_quality.sections["priority_team"].status == "partial"
    assert response.data_quality.sections["team_kpis"].status == "unavailable"


@pytest.mark.asyncio
async def test_missing_contact_queue_marks_overdue_actions_partial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _user(UserRole.recruiter)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="self",
            user_id=operator.id,
            tac_user_ids=[operator.id],
            operator_user_ids=[operator.id],
        ),
    )

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _priority(*_args: Any) -> dict[str, Any]:
        return {"assignments": [], "carry_over": []}

    async def _kpis(*_args: Any) -> dict[str, Any]:
        return {}

    async def _contact_status(*_args: Any) -> dict[str, Any]:
        return {"enabled": True}

    async def _failed_queue(*_args: Any) -> dict[str, Any]:
        raise RuntimeError("contact queue unavailable")

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(dashboard_v2_sources, "load_my_priority_work", _priority)
    monkeypatch.setattr(dashboard_v2_sources, "load_user_kpis", _kpis)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_contact_feature_status",
        _contact_status,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_my_contact_queue",
        _failed_queue,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "cloudtalk_calls_available",
        lambda: False,
    )

    response = await build_my_work_dashboard(
        operator,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
    )

    assert response.data.kpis.overdue_actions.value == 0
    assert response.data.kpis.overdue_actions.quality == "partial"
    assert response.data_quality.sections["contact_queue"].status == "unavailable"


@pytest.mark.asyncio
async def test_malformed_my_work_sources_never_become_complete_zeroes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    operator = _user(UserRole.recruiter)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="self",
            user_id=operator.id,
            tac_user_ids=[operator.id],
            operator_user_ids=[operator.id],
        ),
    )

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _malformed(*_args: Any) -> dict[str, Any]:
        return {}

    async def _contact_status(*_args: Any) -> dict[str, Any]:
        return {"enabled": True}

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_my_priority_work",
        _malformed,
    )
    monkeypatch.setattr(dashboard_v2_sources, "load_user_kpis", _malformed)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_contact_feature_status",
        _contact_status,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_my_contact_queue",
        _malformed,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "cloudtalk_calls_available",
        lambda: True,
    )

    response = await build_my_work_dashboard(
        operator,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
    )

    assert response.data.kpis.plan_completion_pct.value is None
    assert response.data.kpis.overdue_actions.value is None
    assert response.data.kpis.completed_calls.value is None
    assert response.data.kpis.first_verifications.value is None
    assert response.data.kpis.first_recommendations.value is None
    assert response.data.kpis.placements.value is None
    assert response.data_quality.sections["priority_work"].status == "partial"
    assert response.data_quality.sections["personal_kpis"].status == "partial"
    assert response.data_quality.sections["contact_queue"].status == "partial"


@pytest.mark.asyncio
async def test_admin_ops_missing_shapes_never_become_complete_zeroes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = _user(UserRole.admin)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="organization",
            user_id=admin.id,
        ),
    )

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _empty_mapping(*_args: Any) -> dict[str, Any]:
        return {}

    async def _empty_rows(*_args: Any) -> list[Any]:
        return []

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_admin_snapshot",
        _empty_mapping,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_admin_schema_drift",
        _empty_mapping,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_admin_index_coverage",
        _empty_mapping,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_priority_status",
        _empty_mapping,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_priority_alerts",
        _empty_rows,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_traffit_status",
        _empty_mapping,
    )

    response = await build_admin_ops_dashboard(
        object(),  # type: ignore[arg-type]
        admin,
        object(),  # type: ignore[arg-type]
    )

    assert response.data.kpis.critical_readiness.value is None
    assert response.data.kpis.critical_readiness.quality == "unavailable"
    assert response.data.kpis.critical_schema_drift.value is None
    assert response.data.kpis.failed_dead_events.value is None
    assert response.data.kpis.integrations_in_sla.value is None
    assert response.data_quality.sections["admin_snapshot"].status == "partial"
    assert response.data_quality.sections["schema_drift"].status == "partial"
    assert response.data_quality.sections["index_coverage"].status == "partial"
    assert response.data_quality.sections["traffit"].status == "partial"


@pytest.mark.parametrize("tab", ["operations", "executive"])
@pytest.mark.asyncio
async def test_partial_finance_summary_marks_every_summary_kpi_partial(
    monkeypatch: pytest.MonkeyPatch,
    tab: str,
) -> None:
    finance = _user(UserRole.finance)
    scope = ResolvedDashboardScope(
        raw=object(),
        payload=DashboardScopePayload(
            kind="organization",
            user_id=finance.id,
        ),
    )

    async def _scope(*_args: Any) -> ResolvedDashboardScope:
        return scope

    async def _summary(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[dict[str, Any], list[str], str]:
        return (
            {
                "mrr": "100",
                "monthly_margin": "20",
                "margin_pct": "20",
                "consultants": {"utilization_pct": "75"},
            },
            ["One source partition is stale."],
            "partial",
        )

    async def _forecast(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        return SimpleNamespace(fx_missing=False, fx_warnings=[], months=[])

    async def _rows(*_args: Any, **_kwargs: Any) -> list[Any]:
        return []

    async def _finance_tuple(
        *_args: Any,
        **_kwargs: Any,
    ) -> tuple[list[Any], list[str], str]:
        return ([], [], "complete")

    monkeypatch.setattr(dashboard_v2_sources, "resolve_scope", _scope)
    monkeypatch.setattr(dashboard_v2_sources, "load_finance_summary", _summary)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_revenue_forecast",
        _forecast,
    )
    monkeypatch.setattr(dashboard_v2_sources, "load_finance_dso", _rows)
    monkeypatch.setattr(dashboard_v2_sources, "load_overdue_invoices", _rows)
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_finance_trend",
        _finance_tuple,
    )
    monkeypatch.setattr(
        dashboard_v2_sources,
        "load_finance_clients",
        _finance_tuple,
    )

    response = await build_finance_dashboard(
        finance,
        object(),  # type: ignore[arg-type]
        resolve_period("month"),
        tab=tab,
    )

    assert response.data.kpis.mrr_pln.quality == "partial"
    assert response.data.kpis.monthly_margin_pln.quality == "partial"
    assert response.data.kpis.margin_pct.quality == "partial"
    if tab == "executive":
        assert response.data.kpis.utilization_pct.quality == "partial"
