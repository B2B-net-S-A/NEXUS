"""Focused contract tests for type-specific Contract -> Order offboarding."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.client_order_groups import _reduce_legacy_md_budget
from app.api.client_orders import _assert_no_pending_group_line_offboarding
from app.api.dl_alerts import _assert_manual_handling_allowed
from app.models.candidate import Candidate
from app.models.client_order import ClientOrder, ClientOrderStatus
from app.models.client_order_group import ClientOrderGroup, ClientOrderGroupEvent
from app.models.client_order_offboarding import (
    OFFBOARDING_STATUS_PENDING,
    ClientOrderOffboardingCase,
)
from app.models.contract import Contract
from app.models.dl_alert import DL_ALERT_STATUS_NEW, DlAlert
from app.schemas.client_order_group import OrderOffboardingResolutionRequest
from app.services import contract_order_offboarding as offboarding
from app.services import dl_alerts
from app.services.cyfrowy_polsat_orders import CYFROWY_POLSAT_CLIENT_ID
from app.services.multi_consultant_orders import (
    EVENT_CONSULTANT_ENDED,
    EVENT_MD_OFFBOARDING_PENDING,
)

pytestmark = pytest.mark.asyncio


async def test_standard_order_routes_block_a_pending_group_line_case() -> None:
    order = ClientOrder(id=17, client_id=71, contract_id=91, order_group_id=4)
    db = SimpleNamespace(scalar=AsyncMock(return_value=902))

    with pytest.raises(HTTPException) as exc:
        await _assert_no_pending_group_line_offboarding(db, order)

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "offboarding_decision_required"


class _Rows:
    def __init__(self, rows):
        self._rows = list(rows)

    def scalars(self):
        return self

    def unique(self):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(self, *query_rows):
        self._query_rows = iter(query_rows)
        self.added: list[object] = []
        self.statements: list[object] = []

    async def execute(self, statement, *_args, **_kwargs):
        self.statements.append(statement)
        return _Rows(next(self._query_rows))

    def add(self, value):
        self.added.append(value)


def _contract(contract_id: int = 91) -> Contract:
    candidate = Candidate(name="Aleksandra", lastname="Testowa")
    contract = Contract(id=contract_id, client_id=71, currency="EUR")
    contract.candidate = candidate
    return contract


def _group(
    group_id: int,
    order_type: str,
    *,
    shared_md: bool = False,
) -> ClientOrderGroup:
    return ClientOrderGroup(
        id=group_id,
        client_id=71,
        order_number=f"PO-{group_id}",
        start_date=date(2026, 1, 1),
        order_type=order_type,
        is_cost_based=order_type == "cost",
        is_md_budget_based=shared_md,
        md_budget_total=Decimal("120") if shared_md else None,
        md_budget_remaining=Decimal("87") if shared_md else None,
        md_budget_manual_adjustment=Decimal("0"),
    )


def _order(
    order_id: int,
    *,
    contract: Contract,
    order_type: str,
    group: ClientOrderGroup | None = None,
    starts: date = date(2026, 1, 1),
) -> ClientOrder:
    order = ClientOrder(
        id=order_id,
        client_id=71,
        contract_id=contract.id,
        title=f"Order {order_id}",
        order_type=order_type,
        status=ClientOrderStatus.active,
        start_date=starts,
        end_date=date(2026, 12, 31),
        currency="EUR",
        md_rate_cost=Decimal("900"),
        md_rate_revenue=Decimal("1200"),
        md_manual_adjustment=Decimal("0"),
    )
    order.contract = contract
    order.order_group = group
    if group is not None:
        order.order_group_id = group.id
    return order


async def test_future_effective_date_only_clips_periods_and_cancels_not_started(
    monkeypatch,
):
    today = date(2026, 8, 30)
    effective = today + timedelta(days=14)
    contract = _contract()
    periodic = _order(1, contract=contract, order_type="periodic")
    cost = _order(2, contract=contract, order_type="cost", group=_group(20, "cost"))
    md = _order(3, contract=contract, order_type="md", group=_group(30, "md"))
    never_started = _order(
        4,
        contract=contract,
        order_type="periodic",
        starts=effective + timedelta(days=1),
    )
    db = _FakeDb([periodic, cost, md, never_started])
    ensure_case = AsyncMock()
    emit_alert = AsyncMock()
    monkeypatch.setattr(offboarding, "_ensure_md_case", ensure_case)
    monkeypatch.setattr(offboarding, "emit_md_consultant_ended", emit_alert)

    result = await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=effective,
        actor_id=7,
        today=today,
    )

    assert result.affected_orders == 4
    assert result.cancelled_future == 1
    assert result.periodic_completed == 0
    assert result.cost_completed == 0
    assert result.md_cases_created == 0
    assert never_started.status == ClientOrderStatus.cancelled
    for order in (periodic, cost, md):
        assert order.status == ClientOrderStatus.active
        assert order.end_date == effective
    ensure_case.assert_not_awaited()
    emit_alert.assert_not_awaited()
    assert db.added == []


async def test_offboarding_scope_is_the_ended_contract_not_sibling_clients(
    monkeypatch,
):
    """Jedna zakończona relacja osoba–klient nie zamyka innych kontraktów."""

    effective = date(2026, 8, 30)
    ended_contract = _contract(91)
    ended_contract.candidate_id = 501
    sibling_contract = _contract(92)
    sibling_contract.candidate_id = 501
    sibling_contract.client_id = 72
    linked = _order(1, contract=ended_contract, order_type="periodic")
    unrelated = _order(2, contract=sibling_contract, order_type="periodic")
    unrelated.client_id = 72
    # SQL zwraca wyłącznie linked; unrelated istnieje po to, by utrwalić
    # świadomą decyzję domenową i oczekiwany brak efektu ubocznego.
    db = _FakeDb([], [linked])
    monkeypatch.setattr(
        offboarding, "emit_md_consultant_ended", AsyncMock(return_value=[])
    )

    result = await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=ended_contract.id,
        effective_date=effective,
        today=effective,
    )

    assert result.affected_orders == 1
    assert linked.status == ClientOrderStatus.completed
    assert unrelated.status == ClientOrderStatus.active
    open_orders_sql = str(db.statements[-1])
    assert "client_orders.contract_id =" in open_orders_sql
    assert "contracts.candidate_id" not in open_orders_sql


async def test_effective_offboarding_branches_by_type_and_keeps_shared_pool(
    monkeypatch,
):
    effective = date(2026, 8, 30)
    contract = _contract()
    cost_group = _group(20, "cost")
    legacy_md_group = _group(30, "md")
    shared_md_group = _group(40, "md", shared_md=True)
    periodic = _order(1, contract=contract, order_type="periodic")
    cost = _order(2, contract=contract, order_type="cost", group=cost_group)
    legacy_md = _order(3, contract=contract, order_type="md", group=legacy_md_group)
    legacy_md.md_total = Decimal("50")
    legacy_md.md_remaining = Decimal("50")
    shared_md = _order(4, contract=contract, order_type="md", group=shared_md_group)

    # CP is the deliberate shared-pool variant. Keep the per-line MD fixture
    # in its genuinely legacy (pre explicit-type) shape while making the
    # shared group/client relationship coherent with the production policy.
    contract.client_id = CYFROWY_POLSAT_CLIENT_ID
    legacy_md_group.order_type = None
    for group in (cost_group, legacy_md_group, shared_md_group):
        group.client_id = CYFROWY_POLSAT_CLIENT_ID
    for order in (periodic, cost, legacy_md, shared_md):
        order.client_id = CYFROWY_POLSAT_CLIENT_ID
    db = _FakeDb([], [periodic, cost, legacy_md, shared_md])

    async def recompute(_db, order):
        assert order is legacy_md
        order.md_remaining = Decimal("13.250000")
        return order.md_remaining

    created_cases: list[ClientOrderOffboardingCase] = []

    async def ensure_case(
        _db,
        *,
        order,
        group,
        effective_date,
        remaining_md,
        uses_shared_md_pool,
        actor_id,
    ):
        case = ClientOrderOffboardingCase(
            id=100 + len(created_cases),
            contract_id=order.contract_id,
            order_id=order.id,
            order_group_id=group.id,
            client_id=order.client_id,
            effective_date=effective_date,
            status=OFFBOARDING_STATUS_PENDING,
            version=1,
            uses_shared_md_pool=uses_shared_md_pool,
            remaining_md_snapshot=remaining_md,
            rate_cost_snapshot=order.md_rate_cost,
            rate_revenue_snapshot=order.md_rate_revenue,
            currency_snapshot=order.currency,
            order_number_snapshot=group.order_number,
            created_by_user_id=actor_id,
        )
        created_cases.append(case)
        return case, True

    emit_alert = AsyncMock(return_value=[object()])
    monkeypatch.setattr(offboarding, "recompute_remaining", recompute)
    monkeypatch.setattr(offboarding, "_ensure_md_case", ensure_case)
    monkeypatch.setattr(offboarding, "emit_md_consultant_ended", emit_alert)

    result = await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=effective,
        actor_id=7,
        today=effective,
    )

    assert result.periodic_completed == 1
    assert result.cost_completed == 1
    assert result.md_cases_created == 2
    assert result.md_cases_pending == 2
    assert result.alerts_created == 2
    assert all(
        order.status == ClientOrderStatus.completed
        for order in (periodic, cost, legacy_md, shared_md)
    )
    assert legacy_md.end_date == effective
    assert created_cases[0].remaining_md_snapshot == Decimal("13.250000")
    assert created_cases[0].uses_shared_md_pool is False
    assert created_cases[1].remaining_md_snapshot == Decimal("0.000000")
    assert created_cases[1].uses_shared_md_pool is True
    assert shared_md_group.md_budget_total == Decimal("120")
    assert shared_md_group.md_budget_remaining == Decimal("87")

    events = [item for item in db.added if isinstance(item, ClientOrderGroupEvent)]
    assert [event.event_type for event in events] == [
        EVENT_CONSULTANT_ENDED,
        EVENT_MD_OFFBOARDING_PENDING,
        EVENT_MD_OFFBOARDING_PENDING,
    ]


async def test_negative_remaining_is_snapshotted_as_zero(monkeypatch):
    effective = date(2026, 8, 30)
    contract = _contract()
    group = _group(30, "md")
    order = _order(3, contract=contract, order_type="md", group=group)
    order.md_total = Decimal("10")
    db = _FakeDb([], [order])
    captured: list[Decimal] = []

    async def ensure_case(_db, **kwargs):
        captured.append(kwargs["remaining_md"])
        case = ClientOrderOffboardingCase(
            id=1,
            contract_id=contract.id,
            order_id=order.id,
            order_group_id=group.id,
            client_id=order.client_id,
            effective_date=effective,
            status=OFFBOARDING_STATUS_PENDING,
            version=1,
            uses_shared_md_pool=False,
            remaining_md_snapshot=kwargs["remaining_md"],
        )
        return case, True

    monkeypatch.setattr(
        offboarding, "recompute_remaining", AsyncMock(return_value=Decimal("-2"))
    )
    monkeypatch.setattr(offboarding, "_ensure_md_case", ensure_case)
    monkeypatch.setattr(
        offboarding, "emit_md_consultant_ended", AsyncMock(return_value=[])
    )

    await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=effective,
        today=effective,
    )

    assert captured == [Decimal("0.000000")]


async def test_detached_md_line_completes_without_unresolvable_case(monkeypatch):
    effective = date(2026, 8, 30)
    contract = _contract()
    order = _order(3, contract=contract, order_type="md", group=None)
    order.md_total = Decimal("10")
    db = _FakeDb([], [order])
    ensure_case = AsyncMock()
    emit_alert = AsyncMock()
    monkeypatch.setattr(offboarding, "_ensure_md_case", ensure_case)
    monkeypatch.setattr(offboarding, "emit_md_consultant_ended", emit_alert)

    result = await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=effective,
        today=effective,
    )

    assert order.status == ClientOrderStatus.completed
    assert result.md_cases_created == 0
    assert result.md_cases_pending == 0
    ensure_case.assert_not_awaited()
    emit_alert.assert_not_awaited()


async def test_legacy_remove_reduces_signed_budget_instead_of_faking_consumption():
    md_line = ClientOrder(
        md_total=Decimal("50"),
        md_input_mode="md",
        md_input_value=Decimal("50"),
        md_rate_revenue=Decimal("1200"),
    )
    _reduce_legacy_md_budget(md_line, Decimal("20"))
    assert md_line.md_total == Decimal("30.000000")
    assert md_line.md_input_value == Decimal("30.000000")

    amount_line = ClientOrder(
        md_total=Decimal("50"),
        md_input_mode="amount",
        md_input_value=Decimal("60000"),
        md_rate_revenue=Decimal("1200"),
    )
    _reduce_legacy_md_budget(amount_line, Decimal("20"))
    assert amount_line.md_total == Decimal("30.000000")
    assert amount_line.md_input_value == Decimal("36000.000000")

    adjusted_line = ClientOrder(
        md_total=Decimal("50"),
        md_input_mode="md",
        md_input_value=Decimal("50"),
        md_manual_adjustment=Decimal("10"),
        md_rate_revenue=Decimal("1200"),
    )
    _reduce_legacy_md_budget(adjusted_line, Decimal("60"))
    assert adjusted_line.md_total == Decimal("0.000000")
    assert adjusted_line.md_input_value == Decimal("0.000000")
    assert adjusted_line.md_manual_adjustment == Decimal("0.000000")


@pytest.mark.parametrize("rate_revenue", [None, Decimal("0")])
async def test_legacy_amount_without_positive_rate_fails_before_mutation(
    rate_revenue,
):
    """Niekompletny legacy budget zostaje do korekty, bez częściowego zapisu."""

    amount_line = ClientOrder(
        md_total=Decimal("50"),
        md_input_mode="amount",
        md_input_value=Decimal("60000"),
        md_manual_adjustment=Decimal("5"),
        md_rate_revenue=rate_revenue,
    )

    with pytest.raises(HTTPException) as exc_info:
        _reduce_legacy_md_budget(amount_line, Decimal("20"))

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail["code"] == "invalid_legacy_md_budget"
    assert amount_line.md_total == Decimal("50")
    assert amount_line.md_manual_adjustment == Decimal("5")
    assert amount_line.md_input_mode == "amount"
    assert amount_line.md_input_value == Decimal("60000")


async def test_existing_pending_case_is_reconciled_without_creating_another(
    monkeypatch,
):
    effective = date(2026, 8, 30)
    contract = _contract()
    group = _group(30, "md")
    order = _order(3, contract=contract, order_type="md", group=group)
    order.status = ClientOrderStatus.completed
    case = ClientOrderOffboardingCase(
        id=101,
        contract_id=contract.id,
        order_id=order.id,
        order_group_id=group.id,
        client_id=order.client_id,
        effective_date=effective,
        status=OFFBOARDING_STATUS_PENDING,
        version=1,
        uses_shared_md_pool=False,
        remaining_md_snapshot=Decimal("8"),
        order_number_snapshot=group.order_number,
    )
    case.order = order
    case.order_group = group
    db = _FakeDb([case], [])
    ensure_case = AsyncMock()
    # Real emission is one-off and returns [] on an idempotent replay.
    emit_alert = AsyncMock(return_value=[])
    monkeypatch.setattr(offboarding, "_ensure_md_case", ensure_case)
    monkeypatch.setattr(offboarding, "emit_md_consultant_ended", emit_alert)

    result = await offboarding.apply_contract_order_offboarding(
        db,
        contract_id=contract.id,
        effective_date=effective,
        today=effective,
    )

    assert result.affected_orders == 0
    assert result.md_cases_created == 0
    assert result.md_cases_pending == 1
    assert result.case_ids == (101,)
    ensure_case.assert_not_awaited()
    emit_alert.assert_awaited_once()
    assert db.added == []


async def test_daily_reconciler_creates_alert_after_assignment_gap(monkeypatch):
    effective = date(2026, 8, 30)
    contract = _contract()
    group = _group(30, "md")
    order = _order(3, contract=contract, order_type="md", group=group)
    case = ClientOrderOffboardingCase(
        id=101,
        contract_id=contract.id,
        order_id=order.id,
        order_group_id=group.id,
        client_id=order.client_id,
        effective_date=effective,
        status=OFFBOARDING_STATUS_PENDING,
        version=1,
        uses_shared_md_pool=False,
        remaining_md_snapshot=Decimal("8"),
        order_number_snapshot=group.order_number,
    )
    case.order = order
    case.order_group = group
    db = _FakeDb([case])
    emit_alert = AsyncMock(return_value=[object()])
    monkeypatch.setattr(offboarding, "emit_md_consultant_ended", emit_alert)

    created = await offboarding.reconcile_pending_md_offboarding_alerts(db)

    assert created == 1
    emit_alert.assert_awaited_once()
    assert emit_alert.await_args.kwargs["case_id"] == case.id


async def test_resolution_request_requires_a_coherent_transfer():
    with pytest.raises(ValidationError):
        OrderOffboardingResolutionRequest(
            action="transfer", expected_version=1, target_order_id=44
        )
    with pytest.raises(ValidationError):
        OrderOffboardingResolutionRequest(
            action="remove",
            expected_version=1,
            target_order_id=44,
            rate_basis="recipient",
        )

    request = OrderOffboardingResolutionRequest(
        action="transfer",
        expected_version=3,
        target_order_id=44,
        rate_basis="departing",
    )
    assert request.target_order_id == 44
    assert request.rate_basis == "departing"


async def test_md_alert_is_case_scoped_and_resolution_handles_all_recipients(
    monkeypatch,
):
    db = SimpleNamespace(
        scalar=AsyncMock(return_value="Klient Testowy"),
        execute=AsyncMock(return_value=SimpleNamespace(rowcount=2)),
    )
    monkeypatch.setattr(
        dl_alerts, "dl_user_ids_for_client", AsyncMock(return_value=[8, 9])
    )
    emit = AsyncMock(return_value=[object(), object()])
    monkeypatch.setattr(dl_alerts, "emit", emit)

    created = await dl_alerts.emit_md_consultant_ended(
        db,
        case_id=501,
        client_id=71,
        order_id=3,
        order_group_id=30,
        order_number="PO-30",
        consultant_name="Aleksandra Testowa",
        effective_date=date(2026, 8, 30),
        remaining_md=Decimal("0"),
        uses_shared_md_pool=True,
    )

    assert len(created) == 2
    kwargs = emit.await_args.kwargs
    assert kwargs["entity_key"] == "case:501"
    assert kwargs["offboarding_case_id"] == 501
    assert kwargs["repeat_every_days"] is None
    assert "wspólną pulę MD" in kwargs["message"]

    handled = await dl_alerts.handle_offboarding_case_alerts(
        db, case_id=501, handled_by_user_id=8
    )
    assert handled == 2


async def test_pending_md_alert_cannot_be_manually_marked_handled():
    case = ClientOrderOffboardingCase(
        id=501,
        contract_id=91,
        order_id=3,
        client_id=71,
        effective_date=date(2026, 8, 30),
        status=OFFBOARDING_STATUS_PENDING,
        version=1,
        remaining_md_snapshot=Decimal("8"),
    )
    alert = DlAlert(
        id=700,
        alert_type="md_consultant_ended",
        status=DL_ALERT_STATUS_NEW,
        user_id=8,
        client_id=71,
        offboarding_case_id=case.id,
        title="Decyzja MD",
        message="Podejmij decyzję",
        link="/clients/71?tab=orders",
        dedupe_key="case:501:8",
    )
    alert.offboarding_case = case

    with pytest.raises(HTTPException) as exc:
        _assert_manual_handling_allowed(alert)

    assert exc.value.status_code == 409
    assert alert.status == DL_ALERT_STATUS_NEW
