"""Focused guard contract for the Finance persona cutover.

These tests intentionally inspect endpoint type aliases rather than touching
the database. They catch regressions where a financial route is accidentally
put back behind the legacy ``DeliveryLeadPlus`` role guard.
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from typing import get_type_hints

import pytest
from fastapi import HTTPException

from app.api import (
    candidate_access,
    client_orders,
    clients,
    contract_analytics,
    contracts,
    dynareporter_przetargi,
    financial_adjustments,
    invoices,
    my_clients,
    notifications,
    phase5,
    pipeline,
    rate_benchmarks,
    rate_cards,
    reports,
)
from app.api.deps import AdminUser
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
    return get_type_hints(endpoint, include_extras=True)["current_user"]


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
        pipeline.list_pending_verifications,
        pipeline.accept_verification,
        pipeline.reject_verification,
        contract_analytics.margin_by_contractor,
        phase5.create_rate_history,
        phase5.update_rate_history,
        phase5.delete_rate_history,
    ],
)
def test_rate_exception_and_candidate_pii_finance_endpoints_are_admin_only(endpoint):
    assert _current_user_annotation(endpoint) == AdminUser


@pytest.mark.parametrize(
    "endpoint",
    [
        contract_analytics.utilization,
        contract_analytics.role_client_mix,
        contract_analytics.location_distribution,
        contract_analytics.termination_analysis,
    ],
)
def test_legacy_organization_contract_analytics_are_admin_only(
    endpoint,
):
    assert _current_user_annotation(endpoint) == AdminUser


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


def test_flow_b_admin_keeps_rate_defaults_and_computed_margin_shape():
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
        "rate_client": Decimal("18000"),
        "total_value": None,
        "currency": "PLN",
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


def test_candidate_bearing_export_is_admin_only_and_benchmark_is_finance_read():
    assert _current_user_annotation(contracts.export_contracts) == AdminUser
    assert _current_user_annotation(contracts.contract_benchmark) == FinanceReadUser


def test_legacy_przetargi_identity_projections_are_admin_only():
    assert (
        _current_user_annotation(dynareporter_przetargi.list_consultants) == AdminUser
    )
    assert (
        _current_user_annotation(dynareporter_przetargi.list_allocations) == AdminUser
    )


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
