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

from app.analytics.scope import (
    ScopeKind,
    ensure_recruitment_user_scope,
    ensure_team_scope,
)
from app.api import (
    admin_chats,
    admin_client_portfolio,
    admin_clients_overview,
    calendar,
    calendar_access,
    candidate_access,
    candidate_chat,
    candidate_conflicts,
    champion_suggestions,
    client_order_groups,
    client_orders,
    clients,
    contract_analytics,
    contractors,
    contracts,
    financial_adjustments,
    invoices,
    hiring_managers_analytics,
    job_chat,
    jobs,
    my_clients,
    my_relationships,
    notifications,
    phase5,
    rate_benchmarks,
    rate_cards,
    reports,
)
from app.api.deps import AdminUser, DeliveryLeadPlus
from app.api.financial_access import (
    FinanceApproveUser,
    FinanceManageUser,
    FinanceReadUser,
    redact_financial_fields,
)
from app.services.notification_access import user_can_receive_notification
from app.models.notification import NotificationType
from app.models.contract import RateUnit
from app.models.user import User, UserRole
from app.schemas.my_clients import ClientDashboardResponse, MyClientRow
from app.schemas.client_order import ClientOrderRead
from app.schemas.client_order_group import OrderGroupRead
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


# Bramki tras kontraktów i podpisów oraz zapis kwot kontraktu pilnuje
# ``test_permissions_contracts_rules.py`` — pytają o uprawnienia z ekranu Osoby
# i role, więc sprawdzamy tam zachowanie bramki, a nie tożsamość aliasu.


@pytest.mark.parametrize(
    "role",
    [
        UserRole.delivery_lead,
        UserRole.head_of_recruitment,
        UserRole.talent_community_manager,
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


def test_order_amount_write_guard_allows_finance_manager():
    """Decyzja Artura 22.09.2026: Finanse zmieniają kwoty zamówień."""

    client_orders._assert_order_finance_write_allowed(
        _user(UserRole.finance),
        {"rate_client", "rate_candidate", "total_value"},
    )


@pytest.mark.asyncio
async def test_md_line_rates_are_writable_by_finance_manager():
    assert await client_order_groups._can_write_amounts(
        None, _user(UserRole.finance), 1
    )


async def _order_gate_refusal(endpoint, user: User) -> dict | None:
    """Odmowa bramki uprawnienia trasy zamówień (``None`` = wpuszcza)."""

    gate = _annotated_dependency(_user_annotation(endpoint))
    try:
        assert await gate(current_user=user) is user
    except HTTPException as exc:
        assert exc.status_code == 403
        return exc.detail
    return None


def _with_permissions(role: UserRole, *permissions: str) -> User:
    """Konto z rolą i DOKŁADNIE tymi uprawnieniami (już po zależnościach)."""

    from app.services import permission_catalog

    user = _user(role)
    # Oba zrzuty razem i spójnie: sekcje Delivery/Finanse wynikają z uprawnień.
    user.effective_section_access = permission_catalog.derive_sections(permissions)
    user.effective_action_access = {key: "manage" for key in permissions}
    return user


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        client_orders.update_order,
        client_order_groups.update_order_group,
        client_order_groups.update_line,
    ],
)
async def test_order_patch_routes_admit_order_editors_and_amount_editors(endpoint):
    """PATCH zamówienia, grupy i linii: prowadzenie zamówień albo zmiana kwot."""

    for role in (UserRole.admin, UserRole.finance, UserRole.delivery_lead):
        assert await _order_gate_refusal(endpoint, _user(role)) is None
    # Sama zmiana kwot wystarcza do wejścia — handler zawęża ją do pól kwot.
    amounts_only = _with_permissions(
        UserRole.talent_community_manager,
        "delivery_view",
        "amounts_view",
        "amounts_edit",
    )
    assert await _order_gate_refusal(endpoint, amounts_only) is None
    order_editor = _with_permissions(
        UserRole.talent_community_manager, "delivery_view", "contracts_orders_edit"
    )
    assert await _order_gate_refusal(endpoint, order_editor) is None

    for role in (
        UserRole.talent_community_manager,
        UserRole.head_of_recruitment,
        UserRole.recruiter,
    ):
        refusal = await _order_gate_refusal(endpoint, _user(role))
        assert refusal["code"] == "permission_denied"
        assert refusal["permissions"] == ["contracts_orders_edit", "amounts_edit"]


def test_amount_only_account_changes_only_amount_fields_of_orders():
    """Konto bez prowadzenia zamówień zmienia na PATCH-u wyłącznie kwoty."""

    amounts_only = _with_permissions(
        UserRole.talent_community_manager,
        "delivery_view",
        "amounts_view",
        "amounts_edit",
    )
    client_order_groups._assert_amounts_only_without_order_edit(
        amounts_only, {"rate_cost", "budget_amount"}
    )
    with pytest.raises(HTTPException) as exc_info:
        client_order_groups._assert_amounts_only_without_order_edit(
            amounts_only, {"rate_cost", "order_number", "end_date"}
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail["code"] == "finance_amounts_only"
    assert exc_info.value.detail["fields"] == ["end_date", "order_number"]

    # Finanse prowadzą też zamówienia (02.10.2026) — nie są zawężane do kwot.
    client_order_groups._assert_amounts_only_without_order_edit(
        _user(UserRole.finance), {"order_number", "end_date"}
    )
    client_order_groups._assert_amounts_only_without_order_edit(
        _user(UserRole.delivery_lead), {"order_number"}
    )


def test_order_amount_refusal_names_what_is_missing():
    """``finance_fields_forbidden`` zostaje, a odmowa mówi, czego brakuje."""

    # Prowadzi zamówienia, ale nie widzi kwot → brakuje podglądu kwot.
    order_editor = _with_permissions(
        UserRole.talent_community_manager, "delivery_view", "contracts_orders_edit"
    )
    with pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            order_editor, {"rate_client", "title"}
        )
    detail = exc_info.value.detail
    assert exc_info.value.status_code == 403
    assert detail["code"] == "finance_fields_forbidden"
    assert detail["fields"] == ["rate_client"]
    assert detail["permission"] == "amounts_view"
    assert detail["label"] == "Stawki i kwoty: podgląd"
    assert "Stawki i kwoty: podgląd" in detail["message"]

    # Delivery Lead ma komplet uprawnień — odmowa mówi o portfelu, nie
    # o uprawnieniu.
    with pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            _user(UserRole.delivery_lead), {"rate_client"}, can_finance=False
        )
    detail = exc_info.value.detail
    assert detail["code"] == "finance_fields_forbidden"
    assert detail["message"] == "Ten klient jest poza Twoim portfelem."
    assert "permission" not in detail

    # Bez prowadzenia zamówień i bez zmiany kwot → brakuje zmiany kwot.
    with pytest.raises(HTTPException) as exc_info:
        client_orders._assert_order_finance_write_allowed(
            _user(UserRole.talent_community_manager), {"total_value"}
        )
    assert exc_info.value.detail["permission"] == "amounts_edit"

    # Bez pól kwot bramka milczy także dla konta bez uprawnień do kwot.
    client_orders._assert_order_finance_write_allowed(order_editor, {"title"})


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

    # `rate_unit` NIE wraca już z `_flow_b_finance_kwargs`: jednostkę rozstrzyga
    # endpoint (domyślna jednostka klienta albo jawny wybór) i nadaje ją KAŻDEMU
    # rekordowi, także operacyjnemu bez stawek — dlatego nie ma jej w tych kwargach.
    assert contract_kwargs == {
        "rate_client": Decimal("18000"),
        "rate_candidate": Decimal("14000"),
        "currency": "PLN",
        "rate_client_currency": "PLN",
        "rate_candidate_currency": "PLN",
        "billing_hours_per_month": 168,
    }
    assert order_kwargs == {
        "rate_candidate": Decimal("14000"),
        "rate_client": Decimal("18000"),
        "billing_hours_per_month": 168,
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


def test_candidate_finance_read_is_split_from_candidate_finance_write():
    assert UserRole.finance in candidate_access.CANDIDATE_EXPORT_ROLES
    assert UserRole.finance in candidate_access.CANDIDATE_FINANCE_READ_ROLES
    assert UserRole.finance not in candidate_access.CANDIDATE_FINANCE_ROLES
    assert (
        _current_user_annotation(phase5.list_rate_history)
        == candidate_access.CandidateFinanceReadAccess
    )
    # 17.09.2026: konflikty kandydat↔klient to dane o dopuszczalności, nie
    # finansowe — odczyt za bramką kandydacką (DL z finance=none dostawał 403).
    assert (
        _current_user_annotation(candidate_conflicts.list_conflicts)
        == candidate_access.CandidateSearchAccess
    )
    assert _current_user_annotation(contracts.export_contracts) == FinanceReadUser


@pytest.mark.asyncio
async def test_finance_contractor_scope_is_global():
    # Zakres rostera wyznacza portfel Delivery Leada. Finanse mają podgląd
    # Delivery bez roli DL, więc czytają całą organizację: zapytanie wraca
    # nietknięte i nikt nie pyta bazy o portfel (``db=None``).
    finance = _user(UserRole.finance)
    query = object()

    contractors._require_contractor_access(finance)
    assert await contractors._apply_contractor_scope(query, finance, None) is query


@pytest.mark.asyncio
async def test_finance_analytics_team_and_user_scope_are_organization_wide():
    finance = _user(UserRole.finance)

    team_scope = await ensure_team_scope(None, finance)
    assert team_scope.kind is ScopeKind.organization

    user_scope = await ensure_recruitment_user_scope(None, finance, 999)
    assert user_scope.kind is ScopeKind.user
    assert user_scope.user_id == 999


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


def _with_permissions(user: User, *permissions: str) -> User:
    """Konto z dołączoną polityką: uprawnienia z ekranu i wynikające z nich sekcje."""

    from app.services import permission_catalog as catalog

    held = catalog.close(permissions)
    user.effective_action_access = {key: "manage" for key in held}
    user.effective_section_access = catalog.derive_sections(held)
    return user


def test_finance_reads_global_chats_without_gaining_mutations():
    assert (
        _current_user_annotation(admin_chats.global_chats)
        == admin_chats.GlobalChatsReadUser
    )


@pytest.mark.parametrize(
    "endpoint",
    [
        admin_client_portfolio.preview_client_portfolio_import,
        admin_client_portfolio.list_client_portfolio_import_runs,
        admin_client_portfolio.get_client_portfolio_import_run,
    ],
)
async def test_client_portfolio_audit_follows_the_finance_module_permission(endpoint):
    """Audyt importu portfela czyta posiadacz „Modułu Finanse”, nie lista ról."""

    gate = _annotated_dependency(get_type_hints(endpoint, include_extras=True)["_user"])

    for holder in (
        _user(UserRole.admin),
        _user(UserRole.finance),
        # Uprawnienie nadane osobie spoza domyślnych ról.
        _with_permissions(_user(UserRole.recruiter), "finance_module"),
    ):
        assert await gate(holder) is holder

    for outsider in (
        _user(UserRole.delivery_lead),
        _user(UserRole.head_of_recruitment),
        # Rola Finanse z wyłączonym przełącznikiem „Moduł Finanse”.
        _with_permissions(_user(UserRole.finance), "delivery_view"),
    ):
        with pytest.raises(HTTPException) as denied:
            await gate(outsider)
        assert denied.value.status_code == 403
        assert denied.value.detail["code"] == "permission_denied"
        assert denied.value.detail["permission"] == "finance_module"


@pytest.mark.asyncio
async def test_order_safe_gets_and_rate_bearing_documents_use_distinct_readers():
    """Listy czyta podgląd Delivery; eksporty i pliki — dopiero podgląd kwot."""

    tcm = _user(UserRole.talent_community_manager)
    viewer = _with_permissions(UserRole.recruiter, "delivery_view")
    for endpoint in (
        client_orders.list_contractors_with_orders,
        client_orders.list_active_contracts_for_extension,
        client_orders.get_order,
        client_order_groups.list_order_groups,
        client_order_groups.list_group_events,
        client_order_groups.list_group_history,
        client_order_groups.list_line_consumptions,
    ):
        for user in (tcm, viewer, _user(UserRole.finance)):
            assert await _order_gate_refusal(endpoint, user) is None
        refusal = await _order_gate_refusal(endpoint, _user(UserRole.recruiter))
        assert refusal["permission"] == "delivery_view"

    for endpoint in (
        client_orders.export_client_orders,
        client_orders.download_order_po,
        client_orders.list_contract_order_documents,
        client_orders.list_candidate_order_documents,
        client_order_groups.export_order_groups,
        client_order_groups.download_order_group_file,
    ):
        for role in (UserRole.admin, UserRole.finance, UserRole.delivery_lead):
            assert await _order_gate_refusal(endpoint, _user(role)) is None
        for user in (tcm, viewer):
            refusal = await _order_gate_refusal(endpoint, user)
            assert refusal["code"] == "permission_denied"
            assert refusal["permission"] == "amounts_view"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        client_orders.create_order_extension,
        client_orders.extract_order_pdf,
        client_orders.close_order,
        client_orders.delete_order,
        client_orders.preview_order_deletion,
        client_orders.create_contract_with_order,
        client_orders.replace_order_po,
        client_orders.delete_order_po,
        client_order_groups.list_consultant_options_for_client,
        client_order_groups.extract_order_group_pdf,
        client_order_groups.create_order_group,
        client_order_groups.replace_order_group_file,
        client_order_groups.delete_order_group_file,
        client_order_groups.delete_order_group,
        client_order_groups.delete_line,
        client_order_groups.keep_line_as_history,
        client_order_groups.close_order_group,
        client_order_groups.reopen_order_group,
        client_order_groups.cancel_order_group,
        client_order_groups.restore_order_group,
        client_order_groups.extend_order_group,
        client_order_groups.add_line,
        client_order_groups.add_lines_batch,
        client_order_groups.resolve_md_offboarding_case,
        client_order_groups.take_over_consultant,
        client_order_groups.swap_consultant,
        client_order_groups.upsert_line_consumption,
        client_order_groups.delete_line_consumption,
    ],
)
async def test_order_writes_require_the_order_editing_permission(endpoint):
    """Każdy zapis zamówień: „Kontrakty i zamówienia: tworzenie i edycja”."""

    # Finanse dostały prowadzenie zamówień decyzją z 02.10.2026.
    for role in (UserRole.admin, UserRole.delivery_lead, UserRole.finance):
        assert await _order_gate_refusal(endpoint, _user(role)) is None
    granted = _with_permissions(
        UserRole.talent_community_manager, "delivery_view", "contracts_orders_edit"
    )
    assert await _order_gate_refusal(endpoint, granted) is None

    for role in (
        UserRole.talent_community_manager,
        UserRole.head_of_recruitment,
        UserRole.tac,
        UserRole.recruiter,
    ):
        refusal = await _order_gate_refusal(endpoint, _user(role))
        assert refusal["code"] == "permission_denied"
        assert refusal["permission"] == "contracts_orders_edit"
        assert "Kontrakty i zamówienia: tworzenie i edycja" in refusal["message"]
    # Rola Delivery Leada z wyłączonym prowadzeniem zamówień też odpada.
    switched_off = _with_permissions(
        UserRole.delivery_lead, "delivery_view", "amounts_view", "clients_edit"
    )
    refusal = await _order_gate_refusal(endpoint, switched_off)
    assert refusal["permission"] == "contracts_orders_edit"


def test_tcm_order_projection_redacts_finance_and_file_metadata():
    order = ClientOrderRead.model_construct(
        rate_candidate=Decimal("100"),
        rate_client=Decimal("150"),
        total_value=Decimal("15000"),
        monthly_margin=Decimal("50"),
        currency="PLN",
        rate_client_currency="PLN",
        rate_candidate_currency="PLN",
        filename="purchase-order.pdf",
        has_file=True,
        content_type="application/pdf",
        size_bytes=1234,
    )

    # Konto, które nie widzi kwot klienta (domyślnie TCM), nie dostaje też
    # metadanych pliku PO — przycisk kończyłby się odmową.
    projected = client_orders._order_response_for_user(order, show_finance=False)

    assert projected.rate_candidate is None
    assert projected.rate_client is None
    assert projected.total_value is None
    assert projected.monthly_margin is None
    assert projected.currency is None
    assert projected.filename is None
    assert projected.has_file is False
    assert projected.content_type is None
    assert projected.size_bytes is None


def test_tcm_group_projection_recursively_hides_file_metadata():
    future = OrderGroupRead.model_construct(
        filename="future.pdf",
        has_file=True,
        content_type="application/pdf",
        size_bytes=20,
        file_uploaded_at=SimpleNamespace(),
        future_orders=[],
    )
    group = OrderGroupRead.model_construct(
        filename="current.pdf",
        has_file=True,
        content_type="application/pdf",
        size_bytes=10,
        file_uploaded_at=SimpleNamespace(),
        future_orders=[future],
    )

    client_order_groups._redact_group_document_metadata(group)

    for projected in (group, future):
        assert projected.filename is None
        assert projected.has_file is False
        assert projected.content_type is None
        assert projected.size_bytes is None
        assert projected.file_uploaded_at is None


@pytest.mark.asyncio
async def test_finance_is_org_reader_for_my_clients_without_becoming_a_dl():
    # „Moi klienci”: wejście daje podgląd Delivery (bramka trasy), a cała
    # organizacja to brak portfela Delivery Leada — nie lista ról.
    from app.services.client_access import reads_delivery_organization_wide

    gate = _annotated_dependency(_user_annotation(my_clients.list_my_clients))
    dashboard_gate = _annotated_dependency(
        _current_user_annotation(my_clients.require_client_dashboard_access_after_merge)
    )
    assert dashboard_gate is gate

    for role in (UserRole.finance, UserRole.talent_community_manager):
        reader = _user(role)
        assert await gate(reader) is reader
        assert reads_delivery_organization_wide(reader)

    with pytest.raises(HTTPException) as denied:
        await gate(_user(UserRole.recruiter))
    assert denied.value.status_code == 403
    assert denied.value.detail["permission"] == "delivery_view"

    # Delivery Lead wchodzi, ale zostaje przy swoim portfelu.
    lead = _user(UserRole.delivery_lead)
    assert await gate(lead) is lead
    assert not reads_delivery_organization_wide(lead)


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
        jobs.preview_request_history,
        jobs.list_champion_suggestions,
    ):
        assert _current_user_annotation(endpoint) == jobs.RecruitmentHistoryReadUser

    # 17.09.2026: the Historia tab of a saved recruitment is open to its team
    # (resource guard inside the handler); org readers keep the full view.
    assert _current_user_annotation(jobs.get_request_history) == jobs.OperationalUser

    assert (
        _current_user_annotation(jobs.generate_champion_from_history)
        == DeliveryLeadPlus
    )
    assert _current_user_annotation(jobs.add_candidate_from_history) == DeliveryLeadPlus


def test_champion_suggestion_detail_is_finance_read_and_actions_are_job_editors():
    assert (
        _current_user_annotation(champion_suggestions.get_suggestion)
        == champion_suggestions.ChampionSuggestionReadUser
    )
    for endpoint in (
        champion_suggestions.apply_suggestion_endpoint,
        champion_suggestions.reject_suggestion_endpoint,
        champion_suggestions.rate_suggestion_endpoint,
    ):
        # Od 22.09.2026 zespół rekrutacji też (zakres: ensure_champion_job_editor).
        assert _current_user_annotation(endpoint) == champion_suggestions.JobEditUser


def test_finance_calendar_oversight_is_read_only():
    finance = _user(UserRole.finance)
    event = SimpleNamespace(
        created_by=999,
        operational_owner_id=999,
        status=calendar_access.EventStatus.scheduled,
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


class _ChatDb:
    """Minimalna sesja: ``get`` zwraca obiekt dla istniejących id."""

    def __init__(self, existing_ids: set[int]):
        self.existing_ids = existing_ids

    async def get(self, _model, obj_id):
        return SimpleNamespace(id=obj_id) if obj_id in self.existing_ids else None


@pytest.mark.asyncio
async def test_finance_chat_access_is_the_same_rule_for_read_and_write():
    """Od 23.09.2026 czat czyta i pisze każda rola wewnętrzna, także Finanse.

    Osobnego obejścia „tylko odczyt dla Finansów” już nie ma: odczyt woła tę
    samą bramkę co zapis, a nieistniejący zasób to 404.
    """
    finance = _user(UserRole.finance)
    db = _ChatDb({10, 20})
    await job_chat._require_read_access(db, finance, 10)
    await job_chat._require_member(db, finance, 10)
    await candidate_chat._require_read_access(db, finance, 20)
    await candidate_chat._require_member(db, finance, 20)

    for helper, missing_id in (
        (job_chat._require_read_access, 11),
        (candidate_chat._require_read_access, 21),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await helper(db, finance, missing_id)
        assert exc_info.value.status_code == 404


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint",
    [
        reports.report_delivery_leads,
        reports.report_delivery_lead_trend,
        reports.report_invite_links,
    ],
)
async def test_finance_passes_organization_report_read_guards(endpoint):
    finance = _user(UserRole.finance)
    assert await _parameter_dependency(endpoint)(finance) is finance


def test_destructive_client_management_is_admin_only():
    # Usuwanie klienta przeniesione do `client_deletion` (0307): bramką jest
    # IMIENNE uprawnienie `users.can_delete_clients`, nie rola — rola Finanse
    # bez tej flagi nie usunie klienta, tak jak administrator bez niej.
    from app.api import client_deletion

    assert not hasattr(clients, "delete_client")
    assert (
        _parameter_dependency(client_deletion.delete_client)
        is client_deletion.require_client_deletion_permission
    )
    assert (
        _parameter_dependency(client_deletion.check_client_deletion)
        is client_deletion.require_client_deletion_permission
    )


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


def test_finance_notification_visibility_tracks_section_policy():
    """Finance keeps its broad defaults; Recruiter has no Delivery feed."""
    finance = _user(UserRole.finance)
    recruiter = _user(UserRole.recruiter)

    assert user_can_receive_notification(
        finance, NotificationType.contract_ending, link="/contracts/1"
    )
    assert not user_can_receive_notification(
        recruiter, NotificationType.contract_ending, link="/contracts/1"
    )
    assert user_can_receive_notification(
        finance, NotificationType.candidate_added, link="/candidates/1"
    )
    assert user_can_receive_notification(
        recruiter, NotificationType.candidate_added, link="/candidates/1"
    )


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


def test_embed_diagnostics_is_admin_only():
    # UAT M11-B09: ping Voyage + host/port Qdranta tylko dla admina
    # (jedyny konsument: /settings/diagnostics w sekcji system_admin).
    assert _current_user_annotation(phase5.embed_diagnostics) == AdminUser
