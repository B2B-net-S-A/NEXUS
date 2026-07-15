"""RBAC and schema-redaction tests for legacy contract financial surfaces."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import get_type_hints

import pytest
from fastapi import HTTPException
from pydantic import TypeAdapter

from app.api.candidates import _candidate_history_response_for_user
from app.api.candidates import (
    set_recruitment_client_rate,
    set_recruitment_expected_rate,
)
from app.api.b2b_contract_generator import (
    generate as generate_b2b_contract,
    get_detail as get_b2b_contract_detail,
    render_standalone as render_b2b_contract,
)
from app.api.contract_templates import render_template_for_contract
from app.api.contracts import (
    _contract_response_for_user,
    _require_financial_input_access,
    contract_benchmark,
    contract_rate_history,
    get_contract_draft,
    render_draft_for_print,
)
from app.api.client_contract_amendments import (
    create_amendment,
    delete_amendment,
    send_amendment_to_autenti,
)
from app.api.client_framework_contracts import (
    create_framework_contract,
    delete_framework_contract,
    replace_framework_contract_file,
    send_framework_contract_to_autenti,
    update_framework_contract,
)
from app.api.client_orders import (
    create_contract_with_order,
    create_order_extension,
    delete_order,
    replace_order_po,
    update_order,
)
from app.api.deps import DeliveryLeadPlus, FinancialDlAssignedOrAdmin
from app.api.dynareporter_przetargi import (
    AllocationOperationalRow,
    ConsultantOperationalResponse,
    ProjectOperationalSummary,
)
from app.api.financial_access import has_financial_access, require_financial_access
from app.api.invoices import (
    create_invoice,
    dso_by_client,
    export_invoices_csv,
    get_invoice,
    list_invoices,
    update_invoice,
)
from app.api.phase5 import list_rate_history
from app.api.rate_benchmarks import list_benchmarks
from app.api.rate_cards import get_rate_card, list_rate_cards, suggest_rate
from app.models.client_order import ClientOrderStatus
from app.models.contract import ContractStatus, ContractType, RateUnit
from app.models.user import UserRole
from app.schemas.client_order import (
    ClientOrderOperationalRead,
    ClientOrderRead,
    ContractWithOrdersOperationalRead,
    ContractWithOrdersRead,
)
from app.schemas.contract import (
    ContractDetailResponse,
    ContractorCandidateRef,
    ContractorOperationalListItem,
    ContractOperationalDetailResponse,
    ContractUpdate,
)


class _User:
    def __init__(self, *roles: UserRole):
        self.roles = set(roles)

    def has_any_role(self, *roles: UserRole) -> bool:
        return bool(self.roles.intersection(roles))


_FINANCIAL_KEYS = {
    "rate_candidate",
    "rate_client",
    "framework_rate",
    "target_rate_min",
    "target_rate_max",
    "currency",
    "rate_unit",
    "billing_hours_per_month",
    "margin",
    "candidate_rate_schedule",
    "client_rate_schedule",
    "monthly_rate_candidate",
    "monthly_rate_client",
    "monthly_margin",
    "total_value",
    "expected_rate",
    "client_rate",
    "latest_order_rate_client",
    "latest_order_monthly_margin",
}


def _financial_contract() -> ContractDetailResponse:
    now = datetime.now(timezone.utc)
    return ContractDetailResponse(
        id=1,
        candidate_id=2,
        client_id=3,
        job_id=None,
        start_date=date(2026, 1, 1),
        end_date=None,
        client_order_end_date=None,
        rate_candidate=Decimal("100.00"),
        rate_client=Decimal("150.00"),
        framework_rate=Decimal("160.00"),
        target_rate_min=Decimal("140.00"),
        target_rate_max=Decimal("170.00"),
        currency="PLN",
        rate_unit=RateUnit.hourly,
        billing_hours_per_month=160,
        margin=Decimal("50.00"),
        candidate_rate_schedule=[],
        client_rate_schedule=[],
        contract_type=ContractType.b2b,
        status=ContractStatus.active,
        documents=None,
        created_at=now,
        updated_at=now,
        monthly_rate_candidate=Decimal("16000.00"),
        monthly_rate_client=Decimal("24000.00"),
        monthly_margin=Decimal("8000.00"),
    )


def test_finance_access_uses_union_of_roles() -> None:
    assert not has_financial_access(_User(UserRole.tac))
    assert has_financial_access(_User(UserRole.tac, UserRole.delivery_lead))


def test_financial_guard_fails_closed_for_hor() -> None:
    with pytest.raises(HTTPException) as exc:
        require_financial_access(_User(UserRole.head_of_recruitment))
    assert exc.value.status_code == 403


def test_contract_detail_uses_structurally_redacted_schema() -> None:
    response = _contract_response_for_user(
        _financial_contract(), _User(UserRole.tac), detail=True
    )
    assert isinstance(response, ContractOperationalDetailResponse)
    dumped = TypeAdapter(
        ContractDetailResponse | ContractOperationalDetailResponse
    ).dump_python(response, mode="json")
    assert _FINANCIAL_KEYS.isdisjoint(dumped)
    assert dumped["id"] == 1
    assert dumped["status"] == "active"


def test_secondary_delivery_lead_keeps_financial_contract_schema() -> None:
    financial = _financial_contract()
    response = _contract_response_for_user(
        financial, _User(UserRole.tac, UserRole.delivery_lead), detail=True
    )
    assert response is financial
    assert response.model_dump()["rate_client"] == 150


def test_financial_contract_input_requires_admin_or_delivery_lead() -> None:
    with pytest.raises(HTTPException) as exc:
        _require_financial_input_access(
            ContractUpdate(rate_client=Decimal("200")),
            _User(UserRole.tac),
        )
    assert exc.value.status_code == 403

    _require_financial_input_access(
        ContractUpdate(project_name="Nowy projekt"),
        _User(UserRole.tac),
    )
    _require_financial_input_access(
        ContractUpdate(rate_client=Decimal("200")),
        _User(UserRole.tac, UserRole.delivery_lead),
    )


def test_contractor_operational_schema_omits_rates_and_margin() -> None:
    item = ContractorOperationalListItem(
        contract_id=1,
        candidate=ContractorCandidateRef(
            id=2, name="Jan", lastname="Kowalski", email=None
        ),
        client_name="Klient",
        job_title="Python",
        status=ContractStatus.active,
        start_date=date(2026, 1, 1),
        end_date=None,
        contract_type=ContractType.b2b,
        work_mode=None,
        missing_fields=[],
    )
    assert {"rate_candidate", "rate_client", "rate_unit", "margin"}.isdisjoint(
        item.model_dump()
    )


def test_client_order_operational_schemas_omit_all_finance_fields() -> None:
    now = datetime.now(timezone.utc)
    financial_order = ClientOrderRead(
        id=10,
        client_id=3,
        contract_id=1,
        job_id=None,
        framework_contract_id=None,
        title="PO-1",
        description=None,
        status=ClientOrderStatus.active,
        start_date=date(2026, 1, 1),
        end_date=None,
        rate_client=Decimal("150"),
        total_value=Decimal("120000"),
        currency="PLN",
        filename=None,
        has_file=False,
        content_type=None,
        size_bytes=None,
        created_by_user_id=None,
        notes=None,
        created_at=now,
        updated_at=now,
        monthly_margin=Decimal("8000"),
    )
    operational_order = ClientOrderOperationalRead.model_validate(
        financial_order.model_dump()
    )
    financial_group = ContractWithOrdersRead(
        contract_id=1,
        candidate_id=2,
        candidate_name="Jan Kowalski",
        contract_status="active",
        contract_start_date=date(2026, 1, 1),
        contract_end_date=None,
        rate_candidate=Decimal("100"),
        initial_job_id=None,
        initial_job_title=None,
        latest_order_id=10,
        latest_order_rate_client=Decimal("150"),
        latest_order_monthly_margin=Decimal("8000"),
        orders=[financial_order],
    )
    operational_group = ContractWithOrdersOperationalRead.model_validate(
        financial_group.model_dump()
    )

    assert _FINANCIAL_KEYS.isdisjoint(operational_order.model_dump())
    group_dump = operational_group.model_dump()
    assert _FINANCIAL_KEYS.isdisjoint(group_dump)
    assert _FINANCIAL_KEYS.isdisjoint(group_dump["orders"][0])


def test_candidate_history_omits_recruitment_and_contract_rates_for_tac() -> None:
    response = {
        "candidate_id": 7,
        "jobs": [
            {
                "job_id": 9,
                "client_rate": {"value": 200, "currency": "PLN"},
                "expected_rate": {"value": 150, "currency": "PLN"},
                "latest_stage": "verified",
            }
        ],
        "contracts": [
            {
                "contract_id": 1,
                "rate_candidate": 150,
                "rate_client": 200,
                "currency": "PLN",
                "status": "active",
            }
        ],
    }
    redacted = _candidate_history_response_for_user(response, _User(UserRole.tac))
    assert _FINANCIAL_KEYS.isdisjoint(redacted["jobs"][0])
    assert _FINANCIAL_KEYS.isdisjoint(redacted["contracts"][0])
    assert redacted["jobs"][0]["latest_stage"] == "verified"

    hybrid = _candidate_history_response_for_user(
        response, _User(UserRole.tac, UserRole.delivery_lead)
    )
    assert hybrid["jobs"][0]["client_rate"]["value"] == 200


def test_dynareporter_operational_schemas_omit_financial_fields() -> None:
    consultant = ConsultantOperationalResponse(id=1, name="Jan", is_active=True)
    allocation = AllocationOperationalRow(
        id=1,
        project_id=2,
        project_name="Projekt",
        consultant_id=1,
        consultant_name="Jan",
        month=date(2026, 1, 1),
        hours=Decimal("120"),
    )
    summary = ProjectOperationalSummary(
        project_id=2,
        project_name="Projekt",
        months_count=1,
        total_hours=Decimal("120"),
    )
    forbidden = {
        "default_cost_rate",
        "default_revenue_rate",
        "cost_rate",
        "revenue_rate",
        "revenue",
        "cost",
        "margin",
        "total_revenue",
        "total_cost",
        "other_costs",
        "net_value",
        "margin_pct",
    }
    for row in (consultant, allocation, summary):
        assert forbidden.isdisjoint(row.model_dump())


@pytest.mark.asyncio
async def test_financial_contract_reads_fail_before_database_access() -> None:
    tac = _User(UserRole.tac)
    protected_calls = (
        contract_rate_history(1, tac, None),
        contract_benchmark(1, tac, None),
        get_contract_draft(1, tac, None),
        render_draft_for_print(1, tac, None),
    )
    for call in protected_calls:
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 403


@pytest.mark.parametrize(
    "endpoint",
    [
        pytest.param(list_rate_cards, id="rate-cards-list"),
        pytest.param(suggest_rate, id="rate-cards-suggest"),
        pytest.param(get_rate_card, id="rate-card-detail"),
        pytest.param(generate_b2b_contract, id="b2b-generate"),
        pytest.param(get_b2b_contract_detail, id="b2b-detail"),
        pytest.param(render_b2b_contract, id="b2b-render"),
        pytest.param(render_template_for_contract, id="template-render"),
        pytest.param(set_recruitment_client_rate, id="candidate-client-rate"),
        pytest.param(set_recruitment_expected_rate, id="candidate-expected-rate"),
    ],
)
def test_adjacent_rate_surfaces_use_delivery_lead_plus(endpoint) -> None:  # type: ignore[no-untyped-def]
    hints = get_type_hints(endpoint, include_extras=True)
    assert hints["current_user"] == DeliveryLeadPlus


@pytest.mark.parametrize(
    "endpoint",
    [
        list_benchmarks,
        list_rate_history,
        list_invoices,
        create_invoice,
        dso_by_client,
        export_invoices_csv,
        get_invoice,
        update_invoice,
    ],
)
def test_financial_ledger_reads_and_writes_use_delivery_lead_plus(endpoint) -> None:  # type: ignore[no-untyped-def]
    hints = get_type_hints(endpoint, include_extras=True)
    assert hints["current_user"] == DeliveryLeadPlus


@pytest.mark.parametrize(
    "endpoint",
    [
        create_order_extension,
        update_order,
        delete_order,
        create_contract_with_order,
        replace_order_po,
        create_framework_contract,
        update_framework_contract,
        delete_framework_contract,
        replace_framework_contract_file,
        send_framework_contract_to_autenti,
        create_amendment,
        send_amendment_to_autenti,
        delete_amendment,
    ],
)
def test_client_financial_mutations_require_assigned_dl_or_admin(endpoint) -> None:  # type: ignore[no-untyped-def]
    hints = get_type_hints(endpoint, include_extras=True)
    assert hints["user"] == FinancialDlAssignedOrAdmin


@pytest.mark.asyncio
async def test_candidate_rate_mutations_reject_tac_before_database_access() -> None:
    tac = _User(UserRole.tac)
    for call in (
        set_recruitment_client_rate(1, 2, object(), tac, None),
        set_recruitment_expected_rate(1, 2, object(), tac, None),
    ):
        with pytest.raises(HTTPException) as exc:
            await call
        assert exc.value.status_code == 403
