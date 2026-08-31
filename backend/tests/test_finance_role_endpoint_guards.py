"""Focused guard contract for the Finance persona cutover.

These tests intentionally inspect endpoint type aliases rather than touching
the database. They catch regressions where a financial route is accidentally
put back behind the legacy ``DeliveryLeadPlus`` role guard.
"""

from __future__ import annotations

from decimal import Decimal
from inspect import signature
from types import SimpleNamespace
from typing import get_args, get_type_hints

import pytest
from fastapi import HTTPException

from app.analytics.capabilities import (
    AnalyticsCapability,
    require_dynareporter_section,
)
from app.analytics.scope import (
    ScopeKind,
    ensure_recruitment_user_scope,
    ensure_team_scope,
)
from app.api import (
    admin_chats,
    admin_client_portfolio,
    admin_clients_overview,
    autenti,
    calendar,
    calendar_access,
    candidate_access,
    candidate_chat,
    champion_suggestions,
    client_order_groups,
    client_orders,
    clients,
    contract_analytics,
    contractors,
    contracts,
    cortex,
    dynareporter_przetargi,
    financial_adjustments,
    invoices,
    hiring_managers_analytics,
    job_chat,
    jobs,
    linkedin_metrics,
    my_clients,
    my_relationships,
    notifications,
    phase5,
    pipeline,
    rate_benchmarks,
    rate_cards,
    reports,
    signing,
)
from app.api.deps import AdminUser, DeliveryLeadPlus, HeadOfRecruitmentPlus, TacPlus
from app.api.financial_access import (
    FinanceApproveUser,
    FinanceManageUser,
    FinanceReadUser,
    redact_financial_fields,
)
from app.models.notification import NotificationType
from app.models.contract import RateUnit
from app.models.user import User, UserRole
from app.schemas.my_clients import ClientDashboardResponse, MyClientRow
from app.schemas.new_contractor_order import (
    NewContractorOrderRequest,
    NewContractorOrderResponse,
)


def _current_user_annotation(endpoint):
    return _user_annotation(endpoint, "current_user")


def _user_annotation(endpoint, name: str = "user"):
    return get_type_hints(endpoint, include_extras=True)[name]


def _annotated_dependency(annotation):
    return get_args(annotation)[1].dependency


def _parameter_dependency(endpoint, name: str = "current_user"):
    return signature(endpoint).parameters[name].default.dependency


def _user(role: UserRole) -> User:
    return User(
        id=1,
        email=f"{role.value}@example.com",
        name=role.value,
        role=role,
        roles=[role.value],
        is_active=True,
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        financial_adjustments.list_adjustments,
        invoices.list_invoices,
        invoices.dso_by_client,
        invoices.export_invoices_csv,
        invoices.get_invoice,
        rate_cards.list_rate_cards,
        rate_cards.suggest_rate,
        rate_cards.get_rate_card,
        rate_benchmarks.list_benchmarks,
        reports.report_sales,
        reports.report_tenders,
        reports.report_board,
        contract_analytics.margin_by_client,
        contract_analytics.revenue_forecast,
    ],
)
def test_financial_reads_require_finance_read(endpoint):
    assert _current_user_annotation(endpoint) == FinanceReadUser


@pytest.mark.parametrize(
    "endpoint",
    [
        financial_adjustments.create_adjustment,
        invoices.create_invoice,
        invoices.update_invoice,
        invoices.delete_invoice,
        rate_cards.create_rate_card,
        rate_cards.update_rate_card,
        rate_cards.delete_rate_card,
    ],
)
def test_financial_mutations_require_finance_manage(endpoint):
    assert _current_user_annotation(endpoint) == FinanceManageUser


def test_financial_adjustment_approval_requires_finance_approve():
    assert (
        _current_user_annotation(financial_adjustments.approve_adjustment)
        == FinanceApproveUser
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        pipeline.accept_verification,
        pipeline.reject_verification,
        phase5.create_rate_history,
        phase5.update_rate_history,
        phase5.delete_rate_history,
    ],
)
def test_rate_exception_and_candidate_pii_finance_endpoints_are_admin_only(endpoint):
    assert _current_user_annotation(endpoint) == AdminUser


def test_pending_verifications_are_finance_read_but_approval_stays_admin_only():
    assert (
        _current_user_annotation(pipeline.list_pending_verifications)
        == candidate_access.CandidateFinanceReadAccess
    )
    assert _current_user_annotation(pipeline.accept_verification) == AdminUser
    assert _current_user_annotation(pipeline.reject_verification) == AdminUser


@pytest.mark.parametrize(
    "endpoint",
    [
        contract_analytics.margin_by_contractor,
        contract_analytics.utilization,
        contract_analytics.role_client_mix,
        contract_analytics.location_distribution,
        contract_analytics.termination_analysis,
    ],
)
def test_organization_contract_analytics_are_finance_read(endpoint):
    assert _current_user_annotation(endpoint) == FinanceReadUser


def test_my_clients_financial_none_fields_are_structurally_omitted():
    routes = {route.endpoint: route for route in my_clients.router.routes}
    assert routes[my_clients.list_my_clients].response_model_exclude_none is True
    assert routes[my_clients.client_dashboard].response_model_exclude_none is True

    row = MyClientRow(client_id=1, name="Client", active_orders_count=2).model_dump(
        exclude_none=True
    )
    assert "total_revenue_all_time" not in row
    assert "active_revenue" not in row

    dashboard = ClientDashboardResponse(
        client_id=1,
        client_name="Client",
        active_consultants=3,
    ).model_dump(exclude_none=True)
    for financial_key in (
        "total_revenue_all_time",
        "active_revenue",
        "completed_revenue",
        "currency_breakdown",
        "monthly_margin_total",
        "monthly_margin_pct",
    ):
        assert financial_key not in dashboard


def test_candidate_finance_guard_is_admin_only_to_keep_finance_free_of_pii():
    assert set(candidate_access.CANDIDATE_FINANCE_ROLES) == {UserRole.admin}


@pytest.mark.parametrize(
    "role",
    [
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
def test_contract_amount_write_guard_rejects_non_finance_roles(role):
    with pytest.raises(HTTPException) as exc_info:
        contracts._assert_contract_finance_write_allowed(
            _user(role),
            {
                "rate_candidate",
                "rate_client",
                "candidate_rate_schedule",
                "framework_rate",
            },
        )
    assert getattr(exc_info.value, "status_code", None) == 403


def test_contract_amount_write_guard_allows_admin():
    contracts._assert_contract_finance_write_allowed(
        _user(UserRole.admin),
        {
            "rate_candidate",
            "rate_client",
            "candidate_rate_schedule",
            "framework_rate",
        },
    )


def test_contract_amount_write_guard_rejects_finance_to_avoid_candidate_pii():
    with pytest.raises(HTTPException) as exc_info:
        contracts._assert_contract_finance_write_allowed(
            _user(UserRole.finance),
            {"rate_candidate"},
        )
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize(
    "role",
    [
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.recruiter,
        UserRole.sourcer,
    ],
)
def test_order_amount_write_guard_rejects_non_finance_roles(role):
    with pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            _user(role),
            {"rate_client", "rate_candidate", "total_value"},
        )
    assert getattr(exc_info.value, "status_code", None) == 403


def test_order_amount_write_guard_allows_admin():
    client_orders._assert_order_finance_write_allowed(
        _user(UserRole.admin),
        {"rate_client", "rate_candidate", "total_value"},
    )


def test_order_amount_write_guard_rejects_finance_to_avoid_candidate_pii():
    with pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            _user(UserRole.finance),
            {"rate_client"},
        )
    assert exc_info.value.status_code == 403


def test_flow_b_delivery_lead_can_create_operational_records_without_finance():
    payload = NewContractorOrderRequest(candidate_id=10, title="Operacyjny order")

    contract_kwargs, order_kwargs = client_orders._flow_b_finance_kwargs(
        payload,
        _user(UserRole.delivery_lead),
    )

    assert contract_kwargs == {}
    assert order_kwargs == {}
    for field in (
        "rate_client",
        "rate_candidate",
        "rate_unit",
        "billing_hours_per_month",
        "currency",
        "total_value",
    ):
        assert field not in payload.model_fields_set
        assert getattr(payload, field) is None


def test_flow_b_admin_keeps_rate_defaults_and_order_snapshot_shape():
    payload = NewContractorOrderRequest(
        candidate_id=10,
        title="Pełny order",
        rate_client=Decimal("18000"),
        rate_candidate=Decimal("14000"),
    )

    contract_kwargs, order_kwargs = client_orders._flow_b_finance_kwargs(
        payload,
        _user(UserRole.admin),
    )

    assert contract_kwargs == {
        "rate_client": Decimal("18000"),
        "rate_candidate": Decimal("14000"),
        "currency": "PLN",
        "rate_client_currency": "PLN",
        "rate_candidate_currency": "PLN",
        "rate_unit": RateUnit.monthly,
        "billing_hours_per_month": 160,
    }
    assert order_kwargs == {
        "rate_candidate": Decimal("14000"),
        "rate_client": Decimal("18000"),
        "rate_unit": RateUnit.monthly,
        "billing_hours_per_month": 160,
        "total_value": None,
        "currency": "PLN",
        "rate_client_currency": "PLN",
        "rate_candidate_currency": "PLN",
    }
    response = NewContractorOrderResponse(
        contract_id=1,
        order_id=2,
        candidate_name="Kandydat",
        monthly_margin=None,
    )
    assert response.monthly_margin is None


def test_flow_b_admin_still_requires_both_rates():
    payload = NewContractorOrderRequest(candidate_id=10, title="Brak stawek")
    with pytest.raises(HTTPException) as exc_info:
        client_orders._flow_b_finance_kwargs(payload, _user(UserRole.admin))
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail["code"] == "admin_finance_fields_required"


def test_flow_b_non_admin_explicit_finance_key_is_rejected_even_when_null():
    payload = NewContractorOrderRequest(
        candidate_id=10,
        title="Niepoprawny order",
        rate_client=None,
    )
    with pytest.raises(HTTPException) as exc_info:
        client_orders._flow_b_finance_kwargs(
            payload,
            _user(UserRole.delivery_lead),
        )
    assert exc_info.value.status_code == 403


def test_mixed_contract_and_order_redaction_removes_finance_interpretation():
    contract = SimpleNamespace(
        rate_candidate=1,
        rate_client=2,
        framework_rate=3,
        target_rate_min=4,
        target_rate_max=5,
        margin=1,
        monthly_rate_candidate=1,
        monthly_rate_client=2,
        monthly_margin=1,
        currency="PLN",
        rate_unit=RateUnit.monthly,
        billing_hours_per_month=160,
        candidate_rate_schedule=[1],
        client_rate_schedule=[2],
        framework_rate_schedule=[3],
    )
    order = SimpleNamespace(
        rate_client=2,
        total_value=20,
        monthly_margin=1,
        currency="PLN",
    )

    contracts._redact_contract_finance(contract)
    client_orders._redact_order_finance(order)

    assert contract.currency is None
    assert contract.rate_unit is None
    assert contract.billing_hours_per_month is None
    assert order.currency is None


def test_candidate_bearing_export_and_benchmark_are_finance_read():
    assert _current_user_annotation(contracts.export_contracts) == FinanceReadUser
    assert _current_user_annotation(contracts.contract_benchmark) == FinanceReadUser


@pytest.mark.parametrize(
    "endpoint",
    [
        contracts.list_contracts,
        contracts.export_client_register,
        contracts.list_client_register_subcategories,
        contracts.expiring_contracts,
        contracts.get_contract,
        contracts.contract_activities,
        contracts.contract_rate_history,
        contracts.get_contract_draft,
        contracts.render_draft_for_print,
        contracts.list_contract_documents,
        contracts.download_contract_document,
        contracts.list_contract_amendments,
        contracts.list_onboarding_items,
        contracts.list_contract_equipment,
        contracts.contract_timeline,
    ],
)
def test_contract_business_reads_use_finance_extended_read_guard(endpoint):
    assert _current_user_annotation(endpoint) == contracts.ContractReadUser


@pytest.mark.asyncio
async def test_finance_draft_preview_does_not_persist_lazy_initialization(monkeypatch):
    finance = _user(UserRole.finance)
    contract = SimpleNamespace(
        id=17,
        contract_type="b2b",
        draft_content_html=None,
        draft_template_id=None,
        draft_updated_at=None,
        draft_updated_by=None,
    )
    template = SimpleNamespace(
        id=8,
        name="B2B default",
        contract_type="b2b",
        content_jinja="<p>template</p>",
        is_default=True,
    )

    async def load_contract(*_args, **_kwargs):
        return contract

    async def list_templates(*_args, **_kwargs):
        return [template]

    class ReadOnlyDb:
        def add(self, *_args, **_kwargs):
            raise AssertionError("Finance GET must not add Activity")

        async def flush(self):
            raise AssertionError("Finance GET must not flush writes")

        async def scalar(self, *_args, **_kwargs):
            raise AssertionError("No updated_by lookup is expected")

    monkeypatch.setattr(contracts, "_load_contract_with_relations", load_contract)
    monkeypatch.setattr(
        contracts,
        "_list_templates_for_contract_type",
        list_templates,
    )
    monkeypatch.setattr(
        contracts,
        "_render_draft_body",
        lambda *_args: "<p>Finance preview</p>",
    )

    response = await contracts.get_contract_draft(17, finance, ReadOnlyDb())

    assert response.content_html == "<p>Finance preview</p>"
    assert response.template_id == 8
    assert response.rendered_from_default is True
    assert contract.draft_content_html is None
    assert contract.draft_template_id is None
    assert contract.draft_updated_by is None


@pytest.mark.asyncio
async def test_finance_draft_print_preview_does_not_persist_default_template(
    monkeypatch,
):
    finance = _user(UserRole.finance)
    contract = SimpleNamespace(
        id=17,
        contract_type="b2b",
        draft_content_html=None,
        draft_template_id=None,
        draft_updated_at=None,
        draft_updated_by=None,
        candidate=SimpleNamespace(name="Jan", lastname="Kowalski"),
    )
    template = SimpleNamespace(
        id=8,
        name="B2B default",
        contract_type="b2b",
        content_jinja="<p>template</p>",
        is_default=True,
    )

    async def load_contract(*_args, **_kwargs):
        return contract

    async def list_templates(*_args, **_kwargs):
        return [template]

    class ReadOnlyDb:
        def add(self, *_args, **_kwargs):
            raise AssertionError("Finance print GET must not add ORM rows")

        async def flush(self):
            raise AssertionError("Finance print GET must not flush writes")

        async def commit(self):
            raise AssertionError("Finance print GET must not commit writes")

        async def refresh(self, *_args, **_kwargs):
            raise AssertionError("Finance print GET must not refresh ORM rows")

        async def scalar(self, *_args, **_kwargs):
            raise AssertionError(
                "Finance print GET must not query outside read helpers"
            )

    monkeypatch.setattr(contracts, "_load_contract_with_relations", load_contract)
    monkeypatch.setattr(
        contracts,
        "_list_templates_for_contract_type",
        list_templates,
    )
    monkeypatch.setattr(
        contracts,
        "_render_draft_body",
        lambda *_args: "<p>Finance print preview</p>",
    )

    response = await contracts.render_draft_for_print(17, finance, ReadOnlyDb())

    assert response.status_code == 200
    assert b"Finance print preview" in response.body
    assert contract.draft_content_html is None
    assert contract.draft_template_id is None
    assert contract.draft_updated_at is None
    assert contract.draft_updated_by is None


@pytest.mark.parametrize(
    "endpoint",
    [
        contracts.create_contract,
        contracts.update_contract,
        contracts.delete_contract,
        contracts.upload_contract_document,
        contracts.create_contract_amendment,
        contracts.create_onboarding_item,
        contracts.create_contract_equipment,
    ],
)
def test_contract_mutations_keep_tac_plus(endpoint):
    assert _current_user_annotation(endpoint) == TacPlus


def test_candidate_finance_read_is_split_from_candidate_finance_write():
    assert UserRole.finance in candidate_access.CANDIDATE_EXPORT_ROLES
    assert UserRole.finance in candidate_access.CANDIDATE_FINANCE_READ_ROLES
    assert UserRole.finance not in candidate_access.CANDIDATE_FINANCE_ROLES
    assert (
        _current_user_annotation(phase5.list_rate_history)
        == candidate_access.CandidateFinanceReadAccess
    )
    assert (
        _current_user_annotation(phase5.list_conflicts)
        == candidate_access.CandidateFinanceReadAccess
    )
    assert _current_user_annotation(contracts.export_contracts) == FinanceReadUser


@pytest.mark.asyncio
async def test_finance_passes_cortex_read_guard_and_contractor_scope_is_global():
    finance = _user(UserRole.finance)
    guarded = await _annotated_dependency(cortex.CortexUser)(finance)

    assert guarded is finance
    assert UserRole.finance in contractors._FULL_VISIBILITY_ROLES


@pytest.mark.asyncio
async def test_finance_bypasses_business_section_narrowing_after_capability_check():
    finance = _user(UserRole.finance)
    finance.allowed_sections = []

    for section in ("clients-mrr", "przetargi", "board", "sales-mgmt"):
        guard = require_dynareporter_section(section, AnalyticsCapability.VIEW_FINANCE)
        assert await guard(finance) is finance

    with pytest.raises(HTTPException) as mindy_requires_explicit_grant:
        await require_dynareporter_section(
            "mindy",
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
        )(finance)
    assert mindy_requires_explicit_grant.value.status_code == 403

    finance.allowed_sections = ["mindy"]
    assert (
        await require_dynareporter_section(
            "mindy",
            AnalyticsCapability.VIEW_OPERATIONAL_AGGREGATES,
        )(finance)
        is finance
    )

    with pytest.raises(HTTPException) as no_admin_capability:
        await require_dynareporter_section(
            "sales",
            AnalyticsCapability.ADMIN_ANALYTICS,
        )(finance)
    assert no_admin_capability.value.status_code == 403

    with pytest.raises(HTTPException) as no_admin_section:
        await require_dynareporter_section(
            "admin",
            AnalyticsCapability.VIEW_FINANCE,
        )(finance)
    assert no_admin_section.value.status_code == 403


@pytest.mark.asyncio
async def test_finance_analytics_team_and_user_scope_are_organization_wide():
    finance = _user(UserRole.finance)

    team_scope = await ensure_team_scope(None, finance)
    assert team_scope.kind is ScopeKind.organization

    user_scope = await ensure_recruitment_user_scope(None, finance, 999)
    assert user_scope.kind is ScopeKind.user
    assert user_scope.user_id == 999


@pytest.mark.asyncio
async def test_przetargi_identity_projections_use_the_section_guard():
    finance = _user(UserRole.finance)
    finance.allowed_sections = []

    for endpoint in (
        dynareporter_przetargi.list_consultants,
        dynareporter_przetargi.list_allocations,
    ):
        assert await _parameter_dependency(endpoint)(finance) is finance


def test_finance_reads_client_overview_and_hiring_manager_reports():
    assert (
        get_type_hints(
            admin_clients_overview.clients_overview,
            include_extras=True,
        )["_user"]
        == FinanceReadUser
    )
    assert (
        get_type_hints(
            admin_clients_overview.kpi_by_dl,
            include_extras=True,
        )["_user"]
        == FinanceReadUser
    )
    assert (
        get_type_hints(
            hiring_managers_analytics.hiring_managers_kpi,
            include_extras=True,
        )["_user"]
        == hiring_managers_analytics.HiringManagersReadUser
    )


def test_finance_reads_settings_audit_surfaces_without_gaining_mutations():
    assert (
        _current_user_annotation(admin_chats.global_chats)
        == admin_chats.GlobalChatsReadUser
    )
    for endpoint in (
        admin_client_portfolio.preview_client_portfolio_import,
        admin_client_portfolio.list_client_portfolio_import_runs,
        admin_client_portfolio.get_client_portfolio_import_run,
    ):
        assert (
            get_type_hints(endpoint, include_extras=True)["_user"]
            == admin_client_portfolio.ClientPortfolioReadUser
        )
    for endpoint in (
        linkedin_metrics.list_batch,
        linkedin_metrics.list_linkedin_users,
    ):
        assert (
            get_type_hints(endpoint, include_extras=True)["_user"]
            == linkedin_metrics.LinkedInMetricsReadUser
        )
    assert (
        _current_user_annotation(linkedin_metrics.upsert_batch) == HeadOfRecruitmentPlus
    )
    assert (
        get_type_hints(linkedin_metrics.delete_metric, include_extras=True)["_user"]
        == HeadOfRecruitmentPlus
    )


def test_legacy_order_business_gets_use_finance_extended_reader():
    for endpoint in (
        client_orders.list_active_contracts_for_extension,
        client_orders.get_order,
        client_orders.download_order_po,
        client_orders.list_contract_order_documents,
        client_orders.list_candidate_order_documents,
    ):
        assert _user_annotation(endpoint) == client_orders.UnifiedOrderExportReader

    assert (
        _user_annotation(client_order_groups.list_consultant_options_for_client)
        == client_order_groups.ConsultantOptionsReader
    )
    assert (
        _user_annotation(client_order_groups.add_line)
        == client_order_groups.DlAssignedOrAdmin
    )


def test_finance_is_org_reader_for_my_clients_without_becoming_a_dl():
    assert UserRole.finance in my_clients._MY_CLIENTS_ORGANIZATION_READ_ROLES
    assert UserRole.recruiter not in my_clients._MY_CLIENTS_ORGANIZATION_READ_ROLES


@pytest.mark.asyncio
async def test_finance_reads_all_key_relationships_without_owner_filter():
    class _Result:
        def all(self):
            return []

    class _Db:
        async def execute(self, statement):
            compiled = str(statement.compile(compile_kwargs={"literal_binds": True}))
            assert "key_relationship_owner_id" not in compiled
            return _Result()

    assert (
        await my_relationships.list_my_key_relationships(
            _user(UserRole.finance),
            _Db(),
        )
        == []
    )


def test_recruitment_history_gets_use_finance_extended_reader_only():
    for endpoint in (
        jobs.champion_consultant_suggestions,
        jobs.get_champion_historical_matches,
        jobs.preview_historical_matches_for_new_role,
        jobs.get_request_history,
        jobs.preview_request_history,
        jobs.list_champion_suggestions,
    ):
        assert _current_user_annotation(endpoint) == jobs.RecruitmentHistoryReadUser

    assert (
        _current_user_annotation(jobs.generate_champion_from_history)
        == DeliveryLeadPlus
    )
    assert _current_user_annotation(jobs.add_candidate_from_history) == DeliveryLeadPlus


def test_champion_suggestion_detail_is_finance_read_but_actions_stay_tac_plus():
    assert (
        _current_user_annotation(champion_suggestions.get_suggestion)
        == champion_suggestions.ChampionSuggestionReadUser
    )
    for endpoint in (
        champion_suggestions.apply_suggestion_endpoint,
        champion_suggestions.reject_suggestion_endpoint,
        champion_suggestions.rate_suggestion_endpoint,
    ):
        assert _current_user_annotation(endpoint) == TacPlus


def test_contract_signature_reads_include_finance_without_signature_actions():
    for endpoint in (
        autenti.list_signatures_for_contract,
        autenti.get_signature_detail,
    ):
        assert _current_user_annotation(endpoint) == autenti.ContractSignatureReadUser
    for endpoint in (signing.list_signatures, signing.get_signature):
        assert _current_user_annotation(endpoint) == signing.ContractSignatureReadUser

    for endpoint in (
        autenti.send_contract_for_signature,
        autenti.withdraw_signature,
        signing.send_for_signature,
        signing.withdraw_signature,
    ):
        assert _current_user_annotation(endpoint) == TacPlus


def test_finance_calendar_oversight_is_read_only():
    finance = _user(UserRole.finance)
    event = SimpleNamespace(
        created_by=999,
        attendees=["someone@example.com"],
        description="internal",
    )

    assert calendar_access.user_can_view_event(event, finance)
    assert not calendar_access.user_can_mutate_event(event, finance)
    assert calendar_access.project_event_fields(event, finance) == {
        "attendees": ["someone@example.com"],
        "description": "internal",
    }
    assert str(calendar_access.event_visibility_filter(finance)) == "true"
    assert calendar._resolve_scope_user(999, finance) == 999


@pytest.mark.asyncio
async def test_finance_chat_scope_bypass_exists_only_on_read_helper():
    finance = _user(UserRole.finance)
    await job_chat._require_read_access(None, finance, 10)
    await candidate_chat._require_read_access(None, finance, 20)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        reports.report_delivery_leads,
        reports.report_delivery_lead_trend,
        reports.report_invite_links,
        reports.report_power_calling,
    ],
)
async def test_finance_passes_organization_report_read_guards(endpoint):
    finance = _user(UserRole.finance)
    assert await _parameter_dependency(endpoint)(finance) is finance


def test_destructive_client_management_is_admin_only():
    assert _current_user_annotation(clients.delete_client) == AdminUser


def test_finance_notification_allowlist_contains_only_account_security_types():
    assert notifications._FINANCE_SAFE_NOTIFICATION_TYPES == frozenset(
        {
            NotificationType.password_reset_requested,
            NotificationType.password_changed_by_admin,
        }
    )
    for recruitment_type in (
        NotificationType.candidate_added,
        NotificationType.new_application,
        NotificationType.job_chat_message,
        NotificationType.pending_verification,
    ):
        assert recruitment_type not in notifications._FINANCE_SAFE_NOTIFICATION_TYPES


def test_finance_notification_visibility_matches_operational():
    """Od 19.08 finance widzi feed jak role operacyjne (bez allowlisty).

    Kontrakt: predykat widoczności czystej persony finance jest IDENTYCZNY
    z predykatem recruitera (wszystko poza pending_verification) — a nie
    admin-true() i nie dawna lista „finance-safe"."""
    finance = _user(UserRole.finance)
    recruiter = _user(UserRole.recruiter)

    def rendered(user):
        return str(
            notifications._notification_visibility(user).compile(
                compile_kwargs={"literal_binds": True}
            )
        )

    assert rendered(finance) == rendered(recruiter)
    assert "pending_verification" in rendered(finance)


def test_activity_redaction_covers_job_budget_and_generic_amount_keys():
    redacted = redact_financial_fields(
        {
            "salary_min": 10_000,
            "salary_max": 20_000,
            "budget_pln": 50_000,
            "amount": 7_500,
            "total_value": 60_000,
            "title": "Java Developer",
            "nested": {"salary_currency": "PLN", "status": "published"},
        }
    )

    assert redacted == {
        "title": "Java Developer",
        "nested": {"status": "published"},
    }
